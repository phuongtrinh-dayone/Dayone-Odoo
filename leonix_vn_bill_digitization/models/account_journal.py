from odoo import api, Command, fields, models, _
from odoo.exceptions import UserError, ValidationError
import magic
import base64
import pdfplumber
import os
import re
import io
import xml.etree.ElementTree as ET


class AccountJournal(models.Model):
    _inherit = "account.journal"

    def create_document_from_attachment(self, attachment_ids=None):
        invoices = self._create_document_from_attachment(attachment_ids)
        self.env['account.move'].sudo()._cron_digital()
        messages = self.env['account.move'].get_message_digital()
        notifications = {}
        i = 1
        for message in messages:
            notifications.update({"Notify "+str(i): message})
            i = i+1
        updated_context = dict(self._context)
        updated_context.update({"notifications": notifications})

        action_vals = {
            'name': _('Generated Documents'),
            'domain': [('id', 'in', invoices.ids)],
            'res_model': 'account.move',
            'type': 'ir.actions.act_window',
            'context': updated_context
        }
        if len(invoices) == 1:
            action_vals.update({
                'views': [[False, "form"]],
                'view_mode': 'form',
                'res_id': invoices[0].id,
            })
        else:
            action_vals.update({
                'views': [[False, "list"], [False, "kanban"], [False, "form"]],
                'view_mode': 'list, kanban, form',
            })
        return action_vals

    def _create_document_from_attachment(self, attachment_ids=None):
        """
        Create invoices from the attachments (for instance a Factur-X XML file)
        """
        attachments = self.env['ir.attachment'].browse(attachment_ids)
        if not attachments:
            raise UserError(_("No attachment was provided"))
        invoices = self._create_document(attachments)

        return invoices

    def push_notify(self):
        title = _("Successfully!")
        message = _("Your Action Run Successfully!")
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'sticky': False,
            }
        }

    def check_xml_format(self, attachment):
        data_attachment = attachment.datas.decode('utf-8')
        file_extension = os.path.splitext(attachment.name)[1]
        file_extension = file_extension.lower()
        binary_data = base64.b64decode(data_attachment)
        file_magic = magic.Magic(mime=True, mime_encoding=True)
        file_format = file_magic.from_buffer(binary_data)
        file_extension = file_format.split(';')[0]
        if "xml" in file_extension or file_extension == "text/plain" or file_extension == ".xml":
            return True
        return False

    def list_attachments(self, attachments):
        list_attachments = []
        for attachment in attachments:
            list_attachments.append(attachment)
        return list_attachments

    def _create_document(self, attachments):
        invoices = self.env['account.move']
        with invoices._disable_discount_precision():
            # XML attachments
            list_attachments = self.list_attachments(attachments)

            while len(list_attachments) > 0:
                attachment = list_attachments[0]
                invoice, list_Index = self.merge_document(
                    attachment, list_attachments)
                if invoice:
                    # invoice.extract_can_show_resend_button = False
                    invoice.digital_state = 'waiting_upload'
                    if len(list_Index) > 0:
                        for Index in list_Index[::-1]:
                            list_attachments.pop(Index)
                    invoices += invoice

            # Not have invoice same
            for attachment in list_attachments:
                invoice = False
                if not invoice:
                    invoice = self.env['account.move'].create({})
                    # invoice.extract_can_show_resend_button = False
                    invoice.digital_state = 'waiting_upload'

                invoice.with_context(no_new_invoice=True).message_post(
                    attachment_ids=[attachment.id])
                attachment.write(
                    {'res_model': 'account.move', 'res_id': invoice.id})
                invoices += invoice
        return invoices

    def merge_document(self, attachment, attachments):
        list_Index = []
        index = 0  # Index của attachments
        is_have = False
        list_attachment = []
        if self.check_xml_format(attachment):
            serial, invoice_No, seller_tax_code, buyer_name = self.get_data_xml(
                attachment)
            if serial != False and seller_tax_code != False and invoice_No != False and buyer_name != False:
                for attachment1 in attachments:
                    if self.check_xml_format(attachment1):
                        serial1, invoice_No1, seller_tax_code1, buyer_name1 = self.get_data_xml(
                            attachment1)
                        if seller_tax_code == seller_tax_code1 and serial == serial1 and invoice_No == invoice_No1 and buyer_name == buyer_name1:
                            is_have = True
                            list_attachment.append(attachment1)
                            list_Index.append(index)
                    else:
                        pdf_data = self.get_data_pdf(attachment1)
                        pdf_data_temp=pdf_data.replace(" ", "")
                        if seller_tax_code != "":
                            # Trùng serial , số  hóa đơn và mã số thuế người bán
                            if (seller_tax_code in pdf_data or seller_tax_code in pdf_data_temp) and (serial in pdf_data or serial[1::] in pdf_data) and invoice_No in pdf_data and buyer_name in pdf_data:
                                is_have = True
                                list_attachment.append(attachment1)
                                list_Index.append(index)
                        else:
                            if (serial in pdf_data or serial[1::] in pdf_data) and invoice_No in pdf_data and buyer_name in pdf_data:
                                is_have = True
                                list_attachment.append(attachment1)
                                list_Index.append(index)
                    index = index+1
            else:
                is_have = True
                list_attachment.append(attachment)
                list_Index.append(index)
        else:
            pdf_data = self.get_data_pdf(attachment)
            if pdf_data != "":
                for attachment1 in attachments:
                    if self.check_xml_format(attachment1):
                        serial1, invoice_No1, seller_tax_code1, buyer_name1 = self.get_data_xml(
                            attachment1)
                        pdf_data_temp=pdf_data.replace(" ", "")
                        if seller_tax_code1 != "":
                            # Trùng serial , số  hóa đơn và mã số thuế người bán
                            if (seller_tax_code1 in pdf_data or seller_tax_code1 in pdf_data_temp) and (serial1 in pdf_data or serial1[1::] in pdf_data) and invoice_No1 in pdf_data and buyer_name1 in pdf_data:
                                is_have = True
                                list_attachment.append(attachment1)
                                list_Index.append(index)
                        else:
                            if (serial1 in pdf_data or serial1[1::] in pdf_data) and invoice_No1 in pdf_data and buyer_name1 in pdf_data:
                                is_have = True
                                list_attachment.append(attachment1)
                                list_Index.append(index)
                    else:
                        pdf_data1 = self.get_data_pdf(attachment1)
                        if pdf_data1 == pdf_data:
                            is_have = True
                            list_attachment.append(attachment1)
                            list_Index.append(index)
                    index = index+1
            else:
                is_have = True
                list_attachment.append(attachment)
                list_Index.append(index)

        # list_attachment.append(attachment)
        invoice = self.env['account.move'].create({})
        invoice.with_context(no_new_invoice=True).message_post(
            attachment_ids=[x.id for x in list_attachment])
        for att in list_attachment:
            att.write({'res_model': 'account.move', 'res_id': invoice.id})
        if len(attachments) > 0:
            if is_have:
                return invoice, list_Index
        return False, list_Index

    def get_data_xml(self, attachment):
        try:
            data_attachment = attachment.datas.decode('utf-8')
            decoded_data = base64.b64decode(data_attachment)
            root = ET.fromstring(decoded_data)

            Invoice_Data = root.find(".//DLHDon")
            serial1 = Invoice_Data.find(
                "TTChung/KHMSHDon").text if Invoice_Data.find("TTChung/KHMSHDon") != None and Invoice_Data.find("TTChung/KHMSHDon").text != None else " "

            serial2 = Invoice_Data.find(
                "TTChung/KHHDon").text if Invoice_Data.find("TTChung/KHHDon") != None and Invoice_Data.find("TTChung/KHHDon").text != None else " "
            serial = serial1+serial2
            invoice_No = Invoice_Data.find(
                "TTChung/SHDon").text if Invoice_Data.find("TTChung/SHDon") != None and Invoice_Data.find("TTChung/SHDon").text != None else " ",
            seller_tax_code = Invoice_Data.find(
                "NDHDon/NBan/MST").text if Invoice_Data.find("NDHDon/NBan/MST") != None and Invoice_Data.find("NDHDon/NBan/MST").text != None else " ",
            buyer_name = Invoice_Data.find(
                "NDHDon/NMua/Ten").text if Invoice_Data.find("NDHDon/NMua/Ten") != None and Invoice_Data.find("NDHDon/NMua/Ten").text != None else " "
            return serial, invoice_No[0], seller_tax_code[0], buyer_name
        except:
            return False, False, False, False

    def get_data_pdf(self, attachment):
        try:
            data_attachment = attachment.datas.decode('utf-8')
            binary_data = base64.b64decode(data_attachment)
            text = ""
            with pdfplumber.open(io.BytesIO(binary_data)) as pdf:
                for page in pdf.pages:
                    text1 = page.extract_text()
                    text = text+text1
            return text
        except:
            return ""
