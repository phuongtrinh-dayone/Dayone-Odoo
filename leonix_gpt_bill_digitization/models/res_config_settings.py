from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    openapi_api_key = fields.Char(string="API Key", help="Provide the API key here", config_parameter="leonix_gpt_bill_digitization.openapi_api_key")
    chatgpt_model_id = fields.Many2one('chatgpt.model', 'ChatGPT Model', ondelete='cascade', config_parameter="leonix_gpt_bill_digitization.chatgp_model")