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


json_format="""{
        "serial":"String",
        "invoice_No":"String",
        "date_create":"%Y-%m-%d",
        "due_date":"%Y-%m-%d",
        "term":"String" is term of due day,
        "full_term_conditions":"String",
        "currency":"String",
        "seller_name":"String",
        "seller_tax_code":"String",
        "seller_address":"String",
        "seller_phone":"String",
        "seller_bank_code":"String",
        "seller_bank_name":"String",
        "buyer_name":"String",
        "buyer_address:"String",
        "invoice_line":[{
            "No":"Int",
            "Name": "String",
            "Quantity":"Double" if have ',' remove ',' ,
            "Price":"Double",
            "Discount":"Double"
            "VAT":"Int or 0",
        }],
        "total_after_VAT":"Double"
    }"""

list_log_note=[]

class AccountMove(models.Model):
    _inherit = ['account.move']


    # Cron file xml bo qua PDF
    def cron_xml(self):
        Attachment = self.env['ir.attachment']
        attachments = Attachment.search([('res_model', '=', 'account.move'), ('res_id', '=', self.id)])
        if attachments.exists():
            data_attachments=[x.datas.decode('utf-8') for x in attachments]
            # Neu co nhieu file hoac ko co file
            if len(data_attachments)>1 or len(data_attachments)<1:
                return False
            else:
                data_attachment=data_attachments[0]
                binary_data = base64.b64decode(data_attachment)
                file_format=self.get_file_format(binary_data)
                file_format=file_format.lower()
                # neu file co dinh dang PDF bo qua
                if "pdf" in file_format:
                    return False
                else:
                    self.update_data_invoice()
                    return True




    def _cron_parse(self):
        for rec in self.search([('extract_state', '=', 'waiting_upload'),('state','=','draft')]):
            try:
                with self.env.cr.savepoint(flush=False):
                    rec.cron_xml()
                    # We handle the flush manually so that if an error occurs, e.g. a concurrent update error,
                    # the savepoint will be rollbacked when exiting the context manager
                    self.env.cr.flush()
                self.env.cr.commit()
            except (IntegrityError, OperationalError) as e:
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
        if data.get("in_VN_Invoice")==True:
            street ,state ,country,zip = self.parse_address_XML(data["seller_address"])
        else:
            street ,state ,country,zip = self.parse_address_PDF(data["seller_address"])
        partner_id=self.env['res.partner'].create({
                "name":data["seller_name"],
                "street":street,
                "state_id":state,
                "is_company":True,
                "country_id":country,
                "zip":zip,
                "vat":data["seller_tax_code"],
                "phone":data["seller_phone"],
            })
        return partner_id,True
        return False, False

    # Get Term
    def _get_term(self,data):
        term_id=self.env['account.payment.term'].search([('name','ilike',data)])
        if len(term_id)>=1:
            return term_id[0].id
        list_log_note.append(("No matching term "+ str(data),"warning"))
        return False
    # def get_address_by_GPT
    def get_full_address(self,address):
        try:
            ICP = self.env['ir.config_parameter'].sudo()
            key=ICP.get_param('leonix_gpt_bill_digitization.openapi_api_key')
            gpt_model_id = ICP.get_param('leonix_gpt_bill_digitization.chatgp_model')
            
            gpt_model = 'gpt-3.5-turbo'
            if gpt_model_id:
                gpt_model = self.env['chatgpt.model'].browse(int(gpt_model_id)).name
            
            openai.api_key = key
            messages = [
                    {"role": "system", "content": "pharse this address to odoo contact field and return json format{street1:'String',street2:'String',state'String' is city name,zip :'String or None', country:'String' is nation code} with "+address +" and return json"},
                ]
            response = openai.ChatCompletion.create(
                    model=gpt_model,
                    messages=messages
                )
                # Get the assistant's reply
            reply = response['choices'][0]['message']['content']
            return json.loads(reply)
        
        except openai.error.AuthenticationError:
            raise UserError(_('The API key for Chat GPT may have expired or does not exist. Please update your API key.'))
        except Exception as e:
            if key=="" or key==None or key==False:
                raise UserError(_('API key for ChatGPT is not found. Please update your API key.'))
            else:
                raise UserError(_("ChatGPT is error. Try again"))

    def parse_address_PDF(self,address):
        # Chuyển địa chỉ thành địa chỉ đầy đủ
        address1=self.get_full_address(address=address)
        street1=address1.get('street1') and address1.get('street1') or "",
        street2=address1.get('street2') and address1.get('street2') or "",
        state = address1.get('state') and address1.get('state') or "",
        country = address1.get('country') and address1.get('country') or "",
        zip=address1.get('zip') and address1.get('zip') or False
        # # ------------------Đoán quốc gia----------------------
        country_ids=self.env['res.country'].search([])
        choices_country = country_ids.mapped('code')  # Danh sách các lựa chọn tìm kiếm
        results_country = process.extract(str(country[0]), choices_country, scorer=fuzz.ratio, limit=10)
        results_country=[r for r in results_country if r[1] >= 70]
        matched_country_records = self.env['res.country'].search([('code', 'in', [r[0] for r in results_country])])

        if len(matched_country_records)>0:
            country_id=matched_country_records[0]
        else:
            country_id=False
        # -----------------Đoán tỉnh thành-----------------------  
        if country_id:
            records = self.env['res.country.state'].search([('country_id','=',country_id.id)])
            choices = records.mapped('name')  # Danh sách các lựa chọn tìm kiếm
            results = process.extract(str(state[0]), choices, scorer=fuzz.ratio, limit=10)
            results=[r for r in results if r[1] >= 70]
            
            matched_records = self.env['res.country.state'].search([('name', 'in', [r[0] for r in results])])
            if len(matched_records)>0:
                return street1[0]+ ", " + street2[0] , matched_records[0].id, country_id.id, zip
            else:
                return street1[0]+" "+street2[0]+", "+state[0],False,country_id.id,zip
        return address,False,False ,zip

    def parse_address_XML(self,address):
        parts = address.split(", ")
        street = ", ".join(parts[:-2])
        state = parts[-2]
        # ------------------------------------------------
        country_ids=self.env['res.country'].with_context(lang='vi_VN').search([("name",'=',"Việt Nam")])
        if len(country_ids)>0:
            country_id=country_ids[0]
        else:
            country_id=False
        # ------------------------------------------------  
        if country_id:
            records = self.env['res.country.state'].search([('country_id','=',country_id.id)])
            choices = records.mapped('name')  # Danh sách các lựa chọn tìm kiếm
            results = process.extract(state, choices, scorer=fuzz.ratio, limit=10)
            
            results=[r for r in results if r[1] >= 70]
            matched_records = self.env['res.country.state'].with_context(lang='vi_VN').search([('name', 'in', [r[0] for r in results])])
            if len(matched_records)>0:
                return street, matched_records[0].id, country_id.id,False
            else:
                return ", ".join(parts[:-1]),False,country_id.id,False
        # Street1 , state, country, Zip
        return address ,False ,False ,False

    # Map đơn vị tiền tệ vào hóa đơn
    def _get_currency(self, currency_ocr, partner_id):
        for comparison in ['=ilike', 'ilike']:
            # Nếu có trong tiền tệ của cty thì hoạt động bình thường
            possible_currencies = self.env["res.currency"].search([
                '|', '|',
                ('currency_unit_label', comparison, currency_ocr),
                ('name', comparison, currency_ocr),
                ('symbol', comparison, currency_ocr),
            ])
            if possible_currencies:
                break
            
            else:
                # Nếu đơn vị tiền tệ không tồn tại
                possible_currencies = self.env["res.currency"].search([
                '&',
                ('active','=',False),
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
        results=[r for r in results if r[1] >= 65]
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
            discount=il['Discount'] if 'Discount' in il else 0
            vals = {
                'product':self._get_product(il),
                'name': description,
                'price_unit': unit_price,
                'quantity': quantity,
                'tax_ids': tax_ids,
                'discount':discount
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
                    list_log_note.append(("No matching taxes "+ str(data['VAT']),"warning"))
                return tax_id.id
            elif type=="sale":
                tax_id = self.env['account.tax'].search([('amount','=',int(data['VAT'][:-1])),('type_tax_use','=','sale')],limit=1)
                if not tax_id:
                    list_log_note.append(("No matching taxes "+ str(data['VAT']),"warning"))
                return tax_id.id
        else:
            return False

    def _get_vat_line_PDF(self,data):
        type=self.journal_id.type
        if type=="purchase":
            tax_id = self.env['account.tax'].search([('amount','=',int(data['VAT'])),('type_tax_use','=','purchase')],limit=1)
            if not tax_id and int(data['VAT'])!=0 :
                list_log_note.append(("No matching taxes "+ str(data['VAT']) + " %","warning"))
            return tax_id.id
        elif type=="sale":
            tax_id = self.env['account.tax'].search([('amount','=',int(data['VAT'])),('type_tax_use','=','sale')],limit=1)
            # Neu co thue va thue do khac 0
            if not tax_id and int(data['VAT'])!=0 :
                list_log_note.append(("No matching taxes "+ str(data['VAT'])+ " %","warning"))
            return tax_id.id
        else:
            return False

    # endregion 

    # region Get data XML format
    # Load data XML
    def load_invoice_XML(self,data_attachment,force_write=False):
        self.ensure_one()
        data_convert=self.convert_data_from_xml(data_attachment)
        if data_convert==False:
            return False
        self.mapping_invoice_from_data(data_convert,"XML",force_write=force_write)
        return True

    # Convert data xml thành json
    def convert_data_from_xml(self,data):
        try:
            decoded_data = base64.b64decode(data)

            # Create the XML element tree
            root = ET.fromstring(decoded_data)
            Invoice_Data=root.find(".//DLHDon")
            
            # Thông tin tổng quát

            in_VN_Invoice=True if Invoice_Data!=None else False
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
            total_VAT=Invoice_Data.find("NDHDon/TToan/TgTThue").text  if Invoice_Data.find("NDHDon/TToan/TgTThue")!=None else 0,
            total=Invoice_Data.find("NDHDon/TToan/TgTCThue").text  if Invoice_Data.find("NDHDon/TToan/TgTCThue")!=None else 0,
            total_after_VAT=Invoice_Data.find("NDHDon/TToan/TgTTTBSo").text  if Invoice_Data.find("NDHDon/TToan/TgTTTBSo")!=None else 0
            return [{
                "in_VN_Invoice":in_VN_Invoice,
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
            }]
        except:
            return False
    # endregion
    
    # region Get data PDF format
    def load_invoice_PDF(self,data_attachment,force_write=False):
        self.ensure_one()
        data_text=self.convert_PDF_to_Text(data_attachment)
        data_convert=self.chatGPT_convert_Text_to_JSON(data_text)
        if data_convert==False:
            return False
        self.mapping_invoice_from_data(data_convert,'PDF',force_write=force_write)
        return True

    # Chuyển từ PDF sang text
    def convert_PDF_to_Text(self,pdf_file):
        binary_data = base64.b64decode(pdf_file)
        text=[]
        # Chuyển thành list text
        # Chuyển thành list json 
        with pdfplumber.open(io.BytesIO(binary_data)) as pdf:
                for page in pdf.pages:
                    text1 = page.extract_text()
                    text.append(text1)
                return text
        return []
    
    # Chuyển từ tex sang json dùng chatGPT
    def chatGPT_convert_Text_to_JSON(self,text_list):
        try:
            ICP = self.env['ir.config_parameter'].sudo()
            key=ICP.get_param('leonix_gpt_bill_digitization.openapi_api_key')
            gpt_model_id = ICP.get_param('leonix_gpt_bill_digitization.chatgp_model')
            
            gpt_model = 'gpt-3.5-turbo'
            if gpt_model_id:
                gpt_model = self.env['chatgpt.model'].browse(int(gpt_model_id)).name
            
            openai.api_key = key
            list_data=[]
            for text in text_list:
                data_message="Mapping data from text to json "+text+"for format "+json_format +" if many 'seller_bank_code' get first and if text is not invoice return json" + """{"is_invoice":False}"""
                messages = [
                    {"role": "system", "content": data_message},
                ]
                print("INPUT : "+data_message)
                # Make the API call
                #gpt-4-32k-0314 gpt-3.5-turbo gpt-3.5-turbo-0301
                
                response = openai.ChatCompletion.create(
                    model=gpt_model,
                    messages=messages
                )
                # Get the assistant's reply
                reply = response['choices'][0]['message']['content']
                print("OUTPUT : "+reply)
                data=json.loads(reply)
                # Không phải định dạng hóa đơn trả về false
                if data.get("is_invoice")==False:
                    return False
                # Thêm vào list data trả ra
                list_data.append(data)
            return list_data
        except openai.error.AuthenticationError:
            raise UserError(_('The API key for Chat GPT may have expired or does not exist. Please update your API key.'))
        except openai.error.RateLimitError as e:
            raise UserError(_(e))
        except openai.error.APIError as e:
            raise UserError(_(e)) 
        except Exception as e:
            if key=="" or key==None or key==False:
                raise UserError(_('API key for ChatGPT is not found. Please update your API key.'))
            else:
                raise UserError(_(e))
    # endregion

    # Map data vào hóa đơn
    def mapping_invoice_from_data(self,list_data,type,force_write=False):
        # Clear hết các record của invoice line và nếu hóa đơn quá dài thì chỉ cần thực hiện 1 lần chứ không vào vòng lặp
        if force_write:
            self.invoice_line_ids = [Command.clear()]
        self.invoice_line_ids.unlink()
        for data in list_data:
            date_invoice=data['date_create']
            invoice_id=data['invoice_No']
            serial=data['serial']
            results=data['invoice_line']
            currency=data['currency']
            amount_total=data['total_after_VAT']
            due_date=data.get("due_date") and data.get("due_date") or ""
            term=data.get("term") and data.get("term") or ""
            term_and_condition=data.get("full_term_conditions") and data.get("full_term_conditions")

            if not self.partner_id or force_write:
                partner_id, created = self._get_partner(data)
                if partner_id:
                    self.partner_id = partner_id
            
            context_create_date = fields.Date.context_today(self, self.create_date)
            if date_invoice=="":
                list_log_note.append(("No matching date invoice","warning"))
            if date_invoice!="" and (not self.invoice_date or self.invoice_date == context_create_date or force_write):
                self.invoice_date = date_invoice
            if due_date!="" and (not self.invoice_date_due or self.invoice_date_due == context_create_date or force_write):
                self.invoice_date_due = due_date
            if term!="" and (not self.invoice_payment_term_id or force_write):
                self.invoice_payment_term_id=self._get_term(term)
            if term_and_condition!="" and (not self.narration or force_write):
                self.narration=term_and_condition
            if (not self.ref or force_write):
                if serial=="":
                    self.ref=invoice_id
                else:
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
            # ===============================================
            # if force_write:
            #     self.invoice_line_ids = [Command.clear()]
            # self.invoice_line_ids.unlink()
            # ===============================================
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
                        'tax_ids':[],
                        'discount':ocr_line_vals['discount'],
                    })
                    if ocr_line_vals['tax_ids']!=False:
                        line.tax_ids=False
                        line.write({
                        'tax_ids':[(4, ocr_line_vals['tax_ids'])]
                    })
            # Log NOITICE nếu giá trị của hóa đơn khác với giá trị được odoo tính toán
            if self.amount_total!=float(amount_total):
                list_log_note.append(("The total amount in the invoice differs from the calculation in Odoo","warning"))

    
    # Sự kiện Diligital
    def update_data_invoice(self):
        list_log_note.clear()
        Attachment = self.env['ir.attachment']
        attachments = Attachment.search([('res_model', '=', 'account.move'), ('res_id', '=', self.id)])
        if attachments.exists():
            data_attachments=[x.datas.decode('utf-8') for x in attachments]
            # Xử lý 1 file như bình thường
            if len(data_attachments)==1:
                data_attachment=data_attachments[0]
                binary_data = base64.b64decode(data_attachment)
                file_format=self.get_file_format(binary_data)
                file_format=file_format.lower()
                if "pdf" in file_format:
                    is_create=self.load_invoice_PDF(data_attachment,force_write=False)
                    if is_create==False:
                        raise UserError(_("The attached file is not an invoice. Please select a different attachment and try again!"))
                elif "xml" in file_format or file_format=="text/plain":
                    is_create=self.load_invoice_XML(data_attachment,force_write=False)
                    if is_create==False:
                        raise UserError(_("The attached file is not an invoice or has an unsupported structure. Please select a different attachment and try again."))
                        
                else:
                    raise UserError(_('The file format must be XML or PDF.'))
            # Xử lý nhiều file
            elif len(data_attachments)>1:
                invoice_xml=True
                invoice_pdf=True
                # Chạy một vòng tất cả các hóa đơn xml
                for data_attachment in data_attachments:
                    binary_data = base64.b64decode(data_attachment)
                    file_format=self.get_file_format(binary_data)
                    if "xml" in file_format or file_format=="text/plain":
                        is_create=self.load_invoice_XML(data_attachment,force_write=False)
                        # Nếu tạo hóa đơn thành công dừng chương trinh
                        if is_create:
                            invoice_xml=True
                            break
                        invoice_xml=False
                # Tất cả hóa đơn đều XML không chạy được
                if invoice_xml!=True:
                    for data_attachment in data_attachments:
                        binary_data = base64.b64decode(data_attachment)
                        file_format=self.get_file_format(binary_data)
                        if "pdf" in file_format:
                            is_create=self.load_invoice_PDF(data_attachment,force_write=False)
                        if is_create:
                            invoice_pdf=True
                            break
                        invoice_pdf=False
                # Tất cả các file đều không phải hóa đơn báo lỗi
                if invoice_xml==False and invoice_pdf==False:
                    raise UserError(_('The attached files are not invoices or they have an unsupported structure or they are not PDF or XML files. Please select a different attachment file and try again.'))
        self.log_note()
    # Log cảnh báo lỗi
    def log_note(self):
        logs=list_log_note
        for log in logs:
            if log[1]=="notice":
                note="⚠️ [NOTICE] "+log[0]
            else:
                note="⚠️ [WARNING] "+log[0]
            odoobot = self.env.ref('base.partner_root')
            self.message_post(body=_(note),
                                message_type='comment',
                                subtype_xmlid='mail.mt_note',
                                author_id=odoobot.id)
        list_log_note.clear()
        