from psycopg2 import IntegrityError, OperationalError

from odoo import api, fields, models, _, _lt, Command
from datetime import date
import base64
import logging
import re
import json
from dateutil.relativedelta import relativedelta
import xml.etree.ElementTree as ET

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = ['account.move']

    @api.model
    def _cron_parse(self):
        for rec in self.search([('extract_state', '=', 'waiting_upload')]):
            
            try:
                with self.env.cr.savepoint(flush=False):
                    rec.load_invoice_XML()
                    # We handle the flush manually so that if an error occurs, e.g. a concurrent update error,
                    # the savepoint will be rollbacked when exiting the context manager
                    self.env.cr.flush()
                self.env.cr.commit()
            except (IntegrityError, OperationalError) as e:
                
                _logger.error("Couldn't upload %s with id %d: %s", rec._name, rec.id, str(e))
            
    def load_invoice_XML(self,force_write=False):
        self.ensure_one()
        attachments = self.message_main_attachment_id
        if attachments.exists():
            data_attachments=[x.datas.decode('utf-8') for x in attachments]
            for data_attachment in data_attachments:
                data_convert=self.convert_data_to_xml(data_attachment)
                self.mapping_invoice_from_xml(data_convert,force_write=force_write)

    def convert_data_to_xml(self,data):

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
            "buyer_name":buyer_name[0] if buyer_name!=None else "",
            "buyer_name1":buyer_name1[0] if buyer_name1!=None else "",
            "buyer_tax_code":buyer_tax_code[0] if buyer_tax_code!=None else "",
            "buyer_address":buyer_address[0] if buyer_address!=None else "",
            "invoice_line":record1,
            "total_VAT":total_VAT[0],
            "total":total[0],
            "total_after_VAT":total_after_VAT
        }

    def _domain_company(self):
        return ['|', ('company_id', '=', False), ('company_id', '=', self.company_id.id)]

    def find_partner_id_with_vat(self, vat_number):
        partner_vat = self.env["res.partner"].search([("vat", "=ilike", vat_number), *self._domain_company()], limit=1)
        return partner_vat

    def find_partner_id_with_name(self, partner_name):
        if not partner_name:
            return 0

        partner = self.env["res.partner"].search([("name", "=ilike", partner_name), *self._domain_company()], order='supplier_rank desc', limit=1)
        if partner:
            return partner.id if partner.id != self.company_id.partner_id.id else 0
        return 0

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
        if vat_number:
            partner_id=self.env['res.partner'].create({
                    "name":data["seller_name"],
                    "street":data["seller_address"],
                    "vat":data["seller_tax_code"],
                    "phone":data["seller_phone"],

                })
            return partner_id,True
        return False, False

    def _get_vat_line(self,data):
        if data['VAT'][:-1].isdigit():
            type=self.journal_id.type
            if type=="purchase":
                tax_id = self.env['account.tax'].search([('amount','=',int(data['VAT'][:-1])),('type_tax_use','=','purchase')],limit=1)
                return tax_id.id
            elif type=="sale":
                tax_id = self.env['account.tax'].search([('amount','=',int(data['VAT'][:-1])),('type_tax_use','=','sale')],limit=1)
                return tax_id.id
        else:
            return False

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

        partner_last_invoice_currency = partner_id.invoice_ids[:1].currency_id
        if partner_last_invoice_currency in possible_currencies:
            return partner_last_invoice_currency
        if self.company_id.currency_id in possible_currencies:
            return self.company_id.currency_id
        return possible_currencies[:1]

    def _get_invoice_lines(self, results):
        """
        Get write values for invoice lines.
        """
        self.ensure_one()

        invoice_lines = results
        invoice_lines_to_create = []
        for il in invoice_lines:
            print(il['VAT'][:-1].isdigit(),'--------------------------------------------------')
            tax_ids=self._get_vat_line(il)
            description = il['Name'] if 'Name' in il else "/"
            unit_price = il['Price'] if 'Price' in il else 0
            quantity = il['Quantity'] if 'Quantity' in il else 1.0
            
            vals = {
                'name': description,
                'price_unit': unit_price,
                'quantity': quantity,
                'tax_ids': tax_ids
            }

            invoice_lines_to_create.append(vals)

        return invoice_lines_to_create

    def mapping_invoice_from_xml(self,data,force_write=False):

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
        if date_invoice and (not self.invoice_date or self.invoice_date == context_create_date or force_write):
                self.invoice_date = date_invoice

        if (not self.ref or force_write):
                self.ref = serial+"/"+invoice_id

        if self.quick_edit_mode:
            self.name = serial+"/"+invoice_id
        if currency and (self.currency_id == self.company_currency_id or force_write):
                currency = self._get_currency(currency, self.partner_id)
                if currency:
                    self.currency_id = currency

        add_lines = not self.invoice_line_ids or force_write
        if add_lines:
            if force_write:
                self.invoice_line_ids = [Command.clear()]
            vals_invoice_lines = self._get_invoice_lines(results)
            self.invoice_line_ids = [
                Command.create({'name': line_vals.pop('name')})
                for line_vals in vals_invoice_lines
            ]
            for line, ocr_line_vals in zip(self.invoice_line_ids[-len(vals_invoice_lines):], vals_invoice_lines):
                    line.tax_ids=False
                    line.write({
                        'price_unit': ocr_line_vals['price_unit'],
                        'quantity': ocr_line_vals['quantity'],
                        # 'tax_ids':[(4, ocr_line_vals['tax_ids'])]
                    })
                    if ocr_line_vals['tax_ids']!=False:
                        line.tax_ids=False
                        line.write({
                        'tax_ids':[(4, ocr_line_vals['tax_ids'])]
                    })
    



