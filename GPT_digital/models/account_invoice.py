from psycopg2 import IntegrityError, OperationalError
from odoo import api, fields, models, _, _lt, Command
from odoo.exceptions import UserError, ValidationError
from datetime import date
import io
import json
import pdfplumber
import base64
import logging
import openai
import magic
from fuzzywuzzy import fuzz, process
import xml.etree.ElementTree as ET
_logger = logging.getLogger(__name__)


json_format="""{
        "serial":"String",
        "invoice_No":"String",
        "date_create":"%Y-%m-%d",
        "currency":"String",
        "seller_name":"String",
        "seller_tax_code":"String",
        "seller_address":"String",
        "seller_phone":"String",
        "seller_bank_code":"String",
        "seller_bank_name":"String",
        "buyer_name":"String",
        "buyer_tax_code":"String",
        "buyer_address":"String",
        "invoice_line":[{
            "No":"Int",
            "Name": "String",
            "Quantity":"Int",
            "Price":"Double",
            "Total_price":"Double",
            "VAT":"Int or 0",
            "Total_alter_VAT":"Double"
        }],
        "total_VAT":"Double",
        "total":"Double",
        "total_after_VAT":"Double"
    }"""

list_log_note=[]

class AccountMove(models.Model):
    _inherit = ['account.move']


    # Dừng hoạt động cron hóa đơn theo IPA của odoo 
    @api.model
    def _cron_parse(self):
        pass

    
    # region Xác định file đầu vào
    def get_file_format(self,binary_data):
        # Tạo một đối tượng magic
        file_magic = magic.Magic(mime=True, mime_encoding=True)
    
        # Xác định định dạng của dữ liệu binary
        file_format = file_magic.from_buffer(binary_data)
        
        # Tách lấy phần đuôi của định dạng
        file_extension = file_format.split(';')[0]
        
        return file_extension
    # endregion

    # region Map thông tin từ data vào hóa đơn(account.move)
    # Domain theo company
    def _domain_company(self):
        return ['|', ('company_id', '=', False), ('company_id', '=', self.company_id.id)] 
    
    # Tìm khách hàng theo mã số  thuế
    def find_partner_id_with_vat(self, vat_number):
        partner_vat = self.env["res.partner"].search([("vat", "=ilike", vat_number), *self._domain_company()], limit=1)
        return partner_vat
    
    # Tìm khách hàng theo tên
    def find_partner_id_with_name(self, partner_name):
        if not partner_name:
            return 0

        partner = self.env["res.partner"].search([("name", "=ilike", partner_name), *self._domain_company()], order='supplier_rank desc', limit=1)
        if partner:
            return partner.id if partner.id != self.company_id.partner_id.id else 0
        return 0

    # Map khách hàng vào hóa đơn
    def _get_partner(self, data):
        vat_number=data['seller_tax_code']
        iban=data['seller_bank_code']
        client=data['seller_name']

        self.parse_address(data["seller_address"])

        # Tìm nguời dùng với mã số  thuế
        if vat_number:
            partner_vat = self.find_partner_id_with_vat(vat_number)
            if partner_vat:
                return partner_vat, False
        # Tìm theo số  tài khoản ngân hàng
        if iban:
            bank_account = self.env['res.partner.bank'].search([('acc_number', '=ilike', iban), *self._domain_company()])
            if len(bank_account) == 1:
                return bank_account.partner_id, False
        # Tìm theo tên
        partner_id = self.find_partner_id_with_name(client)
        if partner_id != 0:
            return self.env["res.partner"].browse(partner_id), False
        
        # Create new Partner
        if vat_number:
            street ,state ,country = self.parse_address(data["seller_address"])
            partner_id=self.env['res.partner'].create({
                    "name":data["seller_name"],
                    "street":street,
                    "state_id":state,
                    "is_company":True,
                    "country_id":country,
                    "vat":data["seller_tax_code"],
                    "phone":data["seller_phone"],
                })
            return partner_id,True
        return False, False

    def parse_address(self,address):
        parts = address.split(", ")
        street = ", ".join(parts[:-2])
        state = parts[-2]
        country = parts[-1]
        # ------------------------------------------------
        country_ids=self.env['res.country'].search([])
        choices_country = country_ids.mapped('name')  # Danh sách các lựa chọn tìm kiếm
        results_country = process.extract(country, choices_country, scorer=fuzz.ratio, limit=1)
        matched_country_records = self.env['res.country'].search([('name', 'in', [r[0] for r in results_country])])
        country_id=matched_country_records[0]
        # ------------------------------------------------  
        if country_id:
            records = self.env['res.country.state'].search([('country_id','=',country_id.id)])
            choices = records.mapped('name')  # Danh sách các lựa chọn tìm kiếm
            results = process.extract(state, choices, scorer=fuzz.ratio, limit=10)
            
            results=[r for r in results if r[1] >= 70]
            matched_records = self.env['res.country.state'].search([('name', 'in', [r[0] for r in results])])
            if len(matched_records)>0:
                return street, matched_records[0].id, country_id.id
            else:
                return ", ".join(parts[:-1]),False,country_id.id
        return address,False,False 
    
    # Map đơn vị tiền tệ vào hóa đơn
    def _get_currency(self, currency_ocr, partner_id):
        for comparison in ['=ilike', 'ilike']:
            possible_currencies = self.env["res.currency"].search([
                '|', '|',
                ('currency_unit_label', comparison, currency_ocr),
                ('name', comparison, currency_ocr),
                ('symbol', comparison, currency_ocr),
            ])
            if possible_currencies:
                break
            else:
                list_log_note.append(("No matching currency","notice"))

        partner_last_invoice_currency = partner_id.invoice_ids[:1].currency_id
        if partner_last_invoice_currency in possible_currencies:
            return partner_last_invoice_currency
        if self.company_id.currency_id in possible_currencies:
            return self.company_id.currency_id
        return possible_currencies[:1]

    # 
    def _get_product(self,data):
        records = self.env['product.product'].search([])
        choices = records.mapped('name')  # Danh sách các lựa chọn tìm kiếm
        results = process.extract(data['Name'], choices, scorer=fuzz.ratio, limit=10)
        results=[r for r in results if r[1] >= 70]
        matched_records = self.env['product.product'].search([('name', 'in', [r[0] for r in results])])
        if(len(matched_records)>0):
            return matched_records[0].id
        return False
        
    # Map các dòng chi tiết của hóa đơn
    def _get_invoice_lines(self, results,type):
        """
        Get write values for invoice lines.
        """
        self.ensure_one()

        invoice_lines = results
        invoice_lines_to_create = []
        for il in invoice_lines:
            if type=="PDF":
                tax_ids=self._get_vat_line_PDF(il)
            else:
                tax_ids=self._get_vat_line_XML(il)
            description = il['Name'] if 'Name' in il else "/"
            unit_price = il['Price'] if 'Price' in il else list_log_note.append(("No matching price","warning"))
            quantity = il['Quantity'] if 'Quantity' in il else list_log_note.append(("No matching quantity","warning"))
            
            vals = {
                'product':self._get_product(il),
                'name': description,
                'price_unit': unit_price,
                'quantity': quantity,
                'tax_ids': tax_ids
            }

            invoice_lines_to_create.append(vals)

        return invoice_lines_to_create


    # Map VAT vào hóa đơn
    def _get_vat_line_XML(self,data):
        if data['VAT'][:-1].isdigit():
            type=self.journal_id.type
            if type=="purchase":
                tax_id = self.env['account.tax'].search([('amount','=',int(data['VAT'][:-1])),('type_tax_use','=','purchase')],limit=1)
                if not tax_id:
                    print('1111111')
                    list_log_note.append(("No matching taxes","warning"))
                return tax_id.id
            elif type=="sale":
                tax_id = self.env['account.tax'].search([('amount','=',int(data['VAT'][:-1])),('type_tax_use','=','sale')],limit=1)
                if not tax_id:
                    print('2222222222')
                    list_log_note.append(("No matching taxes","warning"))
                return tax_id.id
        else:
            return False

    def _get_vat_line_PDF(self,data):
        type=self.journal_id.type
        if type=="purchase":
            tax_id = self.env['account.tax'].search([('amount','=',int(data['VAT'])),('type_tax_use','=','purchase')],limit=1)
            if not tax_id and int(data['VAT'])!=0 :
                list_log_note.append(("No matching taxes","warning"))
                print('3333333333')
            return tax_id.id
        elif type=="sale":
            tax_id = self.env['account.tax'].search([('amount','=',int(data['VAT'])),('type_tax_use','=','sale')],limit=1)
            # Neu co thue va thue do khac 0
            if not tax_id and int(data['VAT'])!=0 :
                list_log_note.append(("No matching taxes","warning"))
                print('4444444444')
            return tax_id.id
        else:
            return False

    # endregion 

    # region Get data XML format
    # Load data XML
    def load_invoice_XML(self,force_write=False):
        self.ensure_one()
        attachments = self.message_main_attachment_id
        if attachments.exists():
            data_attachments=[x.datas.decode('utf-8') for x in attachments]
            for data_attachment in data_attachments:
                data_convert=self.convert_data_from_xml(data_attachment)
                self.mapping_invoice_from_data(data_convert,"XML",force_write=force_write)
                

    # Convert data xml thành json
    def convert_data_from_xml(self,data):

        decoded_data = base64.b64decode(data)

        # Create the XML element tree
        root = ET.fromstring(decoded_data)
        Invoice_Data=root.find(".//DLHDon")

        # Thông tin tổng quát
        serial1=Invoice_Data.find("TTChung/KHMSHDon").text if Invoice_Data.find("TTChung/KHMSHDon")!=None else""
        serial2=Invoice_Data.find("TTChung/KHHDon").text if Invoice_Data.find("TTChung/KHHDon")!=None else""
        serial=serial1+serial2
        invoice_No=Invoice_Data.find("TTChung/SHDon").text if Invoice_Data.find("TTChung/SHDon")!=None else "",
        date_create=Invoice_Data.find("TTChung/NLap").text if Invoice_Data.find("TTChung/NLap")!=None else "",
        currency=Invoice_Data.find("TTChung/DVTTe").text if Invoice_Data.find("TTChung/DVTTe")!=None else "",

        # Thông tin người bán            
        seller_name=Invoice_Data.find("NDHDon/NBan/Ten").text if Invoice_Data.find("NDHDon/NBan/Ten")!=None else "",
        seller_tax_code=Invoice_Data.find("NDHDon/NBan/MST").text if Invoice_Data.find("NDHDon/NBan/MST")!=None else "",
        seller_address=Invoice_Data.find("NDHDon/NBan/DChi").text if Invoice_Data.find("NDHDon/NBan/DChi")!=None else "",
        seller_phone=Invoice_Data.find("NDHDon/NBan/SDThoai").text if Invoice_Data.find("NDHDon/NBan/SDThoai")!=None else "",
        seller_bank_code=Invoice_Data.find("NDHDon/NBan/STKNHang").text if Invoice_Data.find("NDHDon/NBan/STKNHang")!=None else "",
        seller_bank_name=Invoice_Data.find("NDHDon/NBan/TNHang").text if Invoice_Data.find("NDHDon/NBan/TNHang")!=None else "",
        # Thông tin người mua
        buyer_name=Invoice_Data.find("NDHDon/NMua/Ten").text if Invoice_Data.find("NDHDon/NMua/Ten")!=None else ""
        buyer_tax_code=Invoice_Data.find("NDHDon/NMua/MST").text if Invoice_Data.find("NDHDon/NMua/MST")!=None else ""
        buyer_address=Invoice_Data.find("NDHDon/NMua/DChi").text if Invoice_Data.find("NDHDon/NMua/DChi")!=None else "",
        buyer_name1=Invoice_Data.find("NDHDon/NMua/HVTNMHang").text if Invoice_Data.find("NDHDon/NMua/HVTNMHang")!=None else "",
        # Record đơn hàng
        record1=[]
        for record in Invoice_Data.findall(".//HHDVu"):
            record1.append({
                "No":record.find("STT").text if record.find("STT").text else "",
                "Code": str(record.find("MHHDVu").text) if record.find("MHHDVu")!=None else "",
                "Name": record.find("THHDVu").text if record.find("THHDVu")!=None else "",
                "Unit":record.find("DVTinh").text if record.find("DVTinh")!=None else "",
                "Quantity":record.find("SLuong").text if record.find("SLuong")!=None else "",
                "Price":record.find("DGia").text if record.find("DGia")!=None else 0,
                "Discount_percent":record.find("TLCKhau").text if record.find("TLCKhau")!=None else 0,
                "Discount_total":record.find("STCKhau").text if record.find("STCKhau")!=None else 0,
                "Total_price":record.find("ThTien").text if record.find("ThTien")!=None else 0,
                "VAT":record.find("TSuat").text if record.find("TSuat")!=None else 0,
            })
        # Tổng tiền
        total_VAT=Invoice_Data.find("TToan/TgTThue") if Invoice_Data.find("TToan/TgTThue")!=None else 0,
        total=Invoice_Data.find("TToan/TgTCThue") if Invoice_Data.find("TToan/TgTCThue")!=None else 0,
        total_after_VAT=Invoice_Data.find("TToan/TgTTTBSo") if Invoice_Data.find("TToan/TgTTTBSo")!=None else 0
        
        return {
            "serial":serial,
            "invoice_No":invoice_No[0],
            "date_create":date_create[0],
            "currency":currency[0],
            "seller_name":seller_name[0],
            "seller_tax_code":seller_tax_code[0],
            "seller_address":seller_address[0],
            "seller_phone":seller_phone[0],
            "seller_bank_code":seller_bank_code[0],
            "seller_bank_name":seller_bank_name[0],
            "buyer_name":buyer_name,
            "buyer_name1":buyer_name1,
            "buyer_tax_code":buyer_tax_code[0] if buyer_tax_code!=None else "",
            "buyer_address":buyer_address[0] if buyer_address!=None else "",
            "invoice_line":record1,
            "total_VAT":total_VAT[0],
            "total":total[0],
            "total_after_VAT":total_after_VAT
        }

    # endregion
    
    # region Get data PDF format
    def load_invoice_PDF(self,force_write=False):
        self.ensure_one()
        attachments = self.message_main_attachment_id
        if attachments.exists():
            data_attachments=[x.datas.decode('utf-8') for x in attachments]
            for data_attachment in data_attachments:
                data_text=self.convert_PDF_to_Text(data_attachment)
                data_convert=self.chatGPT_convert_Text_to_JSON(data_text)

                self.mapping_invoice_from_data(data_convert,'PDF',force_write=force_write)
    
    # Chuyển từ PDF sang text
    def convert_PDF_to_Text(self,pdf_file):
        binary_data = base64.b64decode(pdf_file)
        text=""
        with pdfplumber.open(io.BytesIO(binary_data)) as pdf:
                for page in pdf.pages:
                    text1 = page.extract_text()
                    text=text+text1
        return text
    
    # Chuyển từ tex sang json dùng chatGPT
    def chatGPT_convert_Text_to_JSON(self,text):
        try:
            ICP = self.env['ir.config_parameter'].sudo()
            key=ICP.get_param('GPT_digital.openapi_api_key')
            
            openai.api_key = key
            data_message="Mapping data from text to json "+text+"for format "+json_format +" if many 'seller_bank_code' get first"
            messages = [
                {"role": "system", "content": data_message},
            ]
            # Make the API call
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=messages
            )
        
            # Get the assistant's reply
            reply = response['choices'][0]['message']['content']
            return json.loads(reply)
        # except openai.error.AuthenticationError:
        #     raise UserError(_('API key has expired.'))
        except:
            if key=="" or key==None or key==False:
                raise UserError(_('API key for ChatGPT is not found.'))
            else:
                raise UserError(_('An error occurred during the process, please try again.'))

    # endregion

    # Map data vào hóa đơn
    def mapping_invoice_from_data(self,data,type,force_write=False):

        date_invoice=data['date_create']
        invoice_id=data['invoice_No']
        serial=data['serial']
        results=data['invoice_line']
        currency=data['currency']

        if not self.partner_id or force_write:
            partner_id, created = self._get_partner(data)
            if partner_id:
                self.partner_id = partner_id
        
        context_create_date = fields.Date.context_today(self, self.create_date)
        if date_invoice=="":
            list_log_note.append(("No matching date invoice","warning"))
        if date_invoice!="" and (not self.invoice_date or self.invoice_date == context_create_date or force_write):
            self.invoice_date = date_invoice
        
                

        if (not self.ref or force_write):
            ref=serial+"/"+invoice_id
            self.ref = ref
            if ref=="/":
                list_log_note.append(("No matching bill reference","notice"))

        if self.quick_edit_mode:
            self.name = serial+"/"+invoice_id
        if currency and (self.currency_id == self.company_currency_id or force_write):
                currency = self._get_currency(currency, self.partner_id)
                if currency:
                    self.currency_id = currency
        # xử lý record line
        if force_write:
            self.invoice_line_ids = [Command.clear()]
        self.invoice_line_ids.unlink()
        vals_invoice_lines = self._get_invoice_lines(results,type)
        self.invoice_line_ids = [
            Command.create({'name': line_vals.pop('name')})
            for line_vals in vals_invoice_lines
        ]
        for line, ocr_line_vals in zip(self.invoice_line_ids[-len(vals_invoice_lines):], vals_invoice_lines):
                line.tax_ids=False
                line.write({
                    'product_id': ocr_line_vals['product'],
                    'price_unit': ocr_line_vals['price_unit'],
                    'quantity': ocr_line_vals['quantity'],
                    'tax_ids':[]
                })
                if ocr_line_vals['tax_ids']!=False:
                    line.tax_ids=False
                    line.write({
                    'tax_ids':[(4, ocr_line_vals['tax_ids'])]
                })
    # Sự kiện Diligital
    def update_data_invoice(self):
        attachments = self.message_main_attachment_id
        
        if attachments.exists():
            data_attachments=[x.datas.decode('utf-8') for x in attachments]
            
            data_attachment=data_attachments[0]
            binary_data = base64.b64decode(data_attachment)
            file_format=self.get_file_format(binary_data)
            file_format=file_format.lower()
            if "pdf" in file_format:
                self.load_invoice_PDF(force_write=False)
            elif "xml" in file_format or file_format=="text/plain":
                self.load_invoice_XML(force_write=False)
            else:
                raise UserError(_('The file format must be XML or PDF.'))
        self.log_note()
    # Log cảnh báo lỗi
    def log_note(self):
        for log in list_log_note:
            if log[1]=="notice":
                note="⚠️ [NOTICE] "+log[0]
            else:
                note="⚠️ [WARNING] "+log[0]
            odoobot = self.env.ref('base.partner_root')
            self.message_post(body=_(note),
                                message_type='comment',
                                subtype_xmlid='mail.mt_note',
                                author_id=odoobot.id)
        list_log_note=[]