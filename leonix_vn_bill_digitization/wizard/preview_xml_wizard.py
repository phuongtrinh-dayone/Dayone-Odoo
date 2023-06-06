from odoo import models, fields, api, _, tools
from odoo.exceptions import UserError
import base64
import xml.etree.ElementTree as ET
from odoo.tools.misc import formatLang


class PreviewXML(models.TransientModel):
    _name = 'account.preview.xml.wizard'

    body_html = fields.Html('Body', sanitize=False)
    is_invoice = fields.Boolean('Is Invoice')

    def get_data_xml(self, active_id):
        try:
            attachment=self.env['ir.attachment'].search([('id', '=', active_id)])
            data_attachment=attachment.datas.decode('utf-8')
            decoded_data = base64.b64decode(data_attachment)
            root = ET.fromstring(decoded_data)
            Invoice_Data=root.find(".//DLHDon")
            if Invoice_Data!=None:
                serial1=Invoice_Data.find("TTChung/KHMSHDon").text if Invoice_Data.find("TTChung/KHMSHDon")!=None else""
                serial2=Invoice_Data.find("TTChung/KHHDon").text if Invoice_Data.find("TTChung/KHHDon")!=None else""
                invoice_Name=Invoice_Data.find("TTChung/THDon").text if Invoice_Data.find("TTChung/THDon")!=None else "",
                invoice_No=Invoice_Data.find("TTChung/SHDon").text if Invoice_Data.find("TTChung/SHDon")!=None else "",
                date_create=Invoice_Data.find("TTChung/NLap").text if Invoice_Data.find("TTChung/NLap")!=None else "",
                
                if date_create!="":
                    year=date_create[0][0:4]
                    month=date_create[0][5:7]
                    day=date_create[0][8:10]
                    date_create={
                        "year":year,
                        "month":month,
                        "day":day
                    }

                currency=Invoice_Data.find("TTChung/DVTTe").text if Invoice_Data.find("TTChung/DVTTe")!=None else "",
                payment_method=Invoice_Data.find("TTChung/HTTToan").text if Invoice_Data.find("TTChung/HTTToan")!=None else "",
                currency1 = self.env['res.currency'].search([('name','=',currency[0])])
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
                        "Price":(formatLang(self.env, float(record.find("DGia").text), currency_obj=currency1)).replace(currency1.symbol, '').strip() if record.find("DGia")!=None else 0,
                        "Discount_percent":record.find("TLCKhau").text if record.find("TLCKhau")!=None else 0,
                        "Discount_total":(formatLang(self.env, float(record.find("STCKhau").text), currency_obj=currency1)).replace(currency1.symbol, '').strip() if record.find("STCKhau")!=None else 0,
                        "Total_price":(formatLang(self.env, float(record.find("ThTien").text), currency_obj=currency1)).replace(currency1.symbol, '').strip()
                         if record.find("ThTien")!=None else 0,
                        "VAT":record.find("TSuat").text if record.find("TSuat")!=None else 0,
                    })
                # Tổng tiền
                total_VAT=Invoice_Data.find("NDHDon/TToan/TgTThue").text  if Invoice_Data.find("NDHDon/TToan/TgTThue")!=None else 0,
                total=Invoice_Data.find("NDHDon/TToan/TgTCThue").text  if Invoice_Data.find("NDHDon/TToan/TgTCThue")!=None else 0,
                total_after_VAT=Invoice_Data.find("NDHDon/TToan/TgTTTBSo").text  if Invoice_Data.find("NDHDon/TToan/TgTTTBSo")!=None else 0
                total_chu=Invoice_Data.find("NDHDon/TToan/TgTTTBChu").text  if Invoice_Data.find("NDHDon/TToan/TgTTTBChu")!=None else ""
                VAT=Invoice_Data.find("NDHDon/TToan/THTTLTSuat/LTSuat/TSuat").text  if Invoice_Data.find("NDHDon/TToan/THTTLTSuat/LTSuat/TSuat")!=None else "",
                # print(VAT)

                
                return {
                    "template_No":serial1,
                    "serial":serial2,
                    "invoice_No":invoice_No[0],
                    "invoice_Name":invoice_Name[0],
                    "date_create":date_create,
                    "currency":currency[0],
                    "payment_method":payment_method[0],
                    "seller_name":seller_name[0],
                    "seller_tax_code":seller_tax_code[0],
                    "seller_address":seller_address[0],
                    "seller_phone":seller_phone[0],
                    "seller_bank_code":seller_bank_code[0],
                    "seller_bank_name":seller_bank_name[0],
                    "buyer_name":buyer_name,
                    "buyer_name1":buyer_name1,
                    "buyer_tax_code":buyer_tax_code if buyer_tax_code!=None else "",
                    "buyer_address":buyer_address[0] if buyer_address!=None else "",
                    "invoice_line":record1,
                    "vat":VAT[0],
                    "total_VAT":(formatLang(self.env, float(total_VAT[0]), currency_obj=currency1)).replace(currency1.symbol, '').strip(),
                    "total":(formatLang(self.env, float(total[0]), currency_obj=currency1)).replace(currency1.symbol, '').strip(),
                    "total_after_VAT":(formatLang(self.env, float(total_after_VAT), currency_obj=currency1)).replace(currency1.symbol, '').strip(),
                    "total_after_VAT_text":total_chu,
                    "currency1":currency1
                }
            else:
                return False
        except:
            return False


    def default_get(self, fields_list):
        # EXTENDS base
        defaults = super().default_get(fields_list)
        active_id = self._context.get('active_id')
        data_xml=self.get_data_xml(active_id)
        if data_xml!=False:
            print('---------------------------------')
            rendered_template = self.env['ir.ui.view']._render_template(
            'leonix_vn_bill_digitization.xml_preview_template_id', data_xml)
            rendered_template = tools.html_sanitize(rendered_template)
            defaults['body_html'] = rendered_template
            pass
        
        return defaults
