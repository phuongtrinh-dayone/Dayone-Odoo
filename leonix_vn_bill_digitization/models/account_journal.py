from odoo import api, Command, fields, models, _
from odoo.exceptions import UserError, ValidationError
import magic
import base64
import pdfplumber
import os
import io
import xml.etree.ElementTree as ET

class AccountJournal(models.Model):
    _inherit = "account.journal"


    def _create_document_from_attachment(self, attachment_ids=None):
        """
        Create invoices from the attachments (for instance a Factur-X XML file)
        """  
        attachments = self.env['ir.attachment'].browse(attachment_ids)
        if not attachments:
            raise UserError(_("No attachment was provided"))
        invoices = self._create_document(attachments)
        return invoices
    
    def check_xml_format(self,attachment):
        data_attachment=attachment.datas.decode('utf-8')
        binary_data = base64.b64decode(data_attachment)
        file_magic = magic.Magic(mime=True, mime_encoding=True)
        file_format = file_magic.from_buffer(binary_data)
        file_extension = file_format.split(';')[0]
        if "xml" in file_extension or file_extension=="text/plain":
            return True
        return False


    def split_attachments(self,attachments):
        xml_attachments=[]
        not_xml_attachments=[]
        for attachment in attachments:
            if self.check_xml_format(attachment):
                xml_attachments.append(attachment)
            else:
                not_xml_attachments.append(attachment)
        return xml_attachments,not_xml_attachments

    def _create_document(self,attachments):
        xml_attachments,not_xml_attachments=self.split_attachments(attachments)
        invoices = self.env['account.move']
        with invoices._disable_discount_precision():
            # XML attachments
            for attachment in xml_attachments:
                decoders = self.env['account.move']._get_create_document_from_attachment_decoders()
                invoice = False
                # for decoder in sorted(decoders, key=lambda d: d[0]):
                #     invoice = decoder[1](attachment)
                #     if invoice:
                #         break
                if not invoice:
                    invoice,index=self.merge_document(attachment,not_xml_attachments)
                    
                    invoice.extract_can_show_resend_button = False
                    invoice.extract_state = 'waiting_upload'
                    self.env.ref('account_invoice_extract.ir_cron_ocr_parse')._trigger()
                    if index!="False":
                        not_xml_attachments.pop(index)
                invoices += invoice
            # Not XML attachments
            for attachment in not_xml_attachments:
                decoders = self.env['account.move']._get_create_document_from_attachment_decoders()
                invoice = False
                # for decoder in sorted(decoders, key=lambda d: d[0]):
                #     invoice = decoder[1](attachment)
                #     if invoice:
                #         break
                if not invoice:
                    invoice = self.env['account.move'].create({})
                    
                    invoice.extract_can_show_resend_button = False
                    invoice.extract_state = 'waiting_upload'
                    self.env.ref('account_invoice_extract.ir_cron_ocr_parse')._trigger()
                invoice.with_context(no_new_invoice=True).message_post(attachment_ids=[attachment.id])
                attachment.write({'res_model': 'account.move', 'res_id': invoice.id})
                invoices += invoice
        return invoices  


    def merge_document(self,attachment,not_xml_attachments):
        index=0;#Index của not_xml_attachments
        is_have_pdf=False
        list_attachment=[]
        attachment_name=os.path.splitext(attachment.name)[0]
        print(attachment_name)
        serial,invoice_No,seller_tax_code,buyer_name=self.get_data_xml(attachment)
        if serial!=False and seller_tax_code!=False and invoice_No!=False and buyer_name!=False:
            for attachment1 in not_xml_attachments:
                attachment1_name=os.path.splitext(attachment1.name)[0]
                # Nếu trùng tên
                if attachment_name==attachment1_name:
                    is_have_pdf=True
                    list_attachment.append(attachment1)
                    break
                pdf_data=self.get_data_pdf(attachment1)
                if seller_tax_code!="":
                    # Trùng serial , số  hóa đơn và mã số thuế người bán
                    if seller_tax_code in pdf_data and serial in pdf_data and invoice_No in pdf_data and buyer_name in pdf_data:
                        is_have_pdf=True
                        list_attachment.append(attachment1)
                        break
                else:
                    if serial in pdf_data and invoice_No in pdf_data and buyer_name in pdf_data:
                        is_have_pdf=True
                        list_attachment.append(attachment1)
                        break
                index=index+1

        list_attachment.append(attachment)
        invoice = self.env['account.move'].create({})
        invoice.with_context(no_new_invoice=True).message_post(attachment_ids=[x.id for x in list_attachment])
        for att in list_attachment:
            att.write({'res_model': 'account.move', 'res_id': invoice.id})
        
        if is_have_pdf:
            return invoice,index
        return invoice,"False"
        
    def get_data_xml(self,attachment):
        try :
            data_attachment=attachment.datas.decode('utf-8')
            decoded_data = base64.b64decode(data_attachment)
            root = ET.fromstring(decoded_data)

            Invoice_Data=root.find(".//DLHDon")
            serial1=Invoice_Data.find("TTChung/KHMSHDon").text if Invoice_Data.find("TTChung/KHMSHDon")!=None else""
            serial2=Invoice_Data.find("TTChung/KHHDon").text if Invoice_Data.find("TTChung/KHHDon")!=None else""
            serial=serial1+serial2
            invoice_No=Invoice_Data.find("TTChung/SHDon").text if Invoice_Data.find("TTChung/SHDon")!=None else "",
            seller_tax_code=Invoice_Data.find("NDHDon/NBan/MST").text if Invoice_Data.find("NDHDon/NBan/MST")!=None else "",
            buyer_name=Invoice_Data.find("NDHDon/NMua/Ten").text if Invoice_Data.find("NDHDon/NMua/Ten")!=None else ""   
            return serial,invoice_No[0],seller_tax_code[0],buyer_name[0]
        except:
            return False,False,False,False
    def get_data_pdf(self,attachment):
        try:
            data_attachment=attachment.datas.decode('utf-8')
            binary_data = base64.b64decode(data_attachment)
            text=""
            with pdfplumber.open(io.BytesIO(binary_data)) as pdf:
                    for page in pdf.pages:
                        text1 = page.extract_text()
                        text=text+text1
            return text
        except:
            return ""
