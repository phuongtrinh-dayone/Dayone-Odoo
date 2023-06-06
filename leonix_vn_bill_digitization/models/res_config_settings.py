from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    tdt_username=fields.Char(string="Username", help="username of thuedientu.gdt.gov.vn", config_parameter="leonix_vn_bill_digitization.tdt_username")
    tdt_password=fields.Char(string="Password", help="password of thuedientu.gdt.gov.vn", config_parameter="leonix_vn_bill_digitization.tdt_password")