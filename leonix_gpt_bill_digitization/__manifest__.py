{
    'name': 'leonix_gpt_bill_digitization',
    'version': '1.0',
    'category': 'Custom',
    'summary': 'Module for digitizing bills using GPT',
    'author': 'Leonix',
    'website': 'https://leonix.vn',
    'depends' : ['base','account','account_invoice_extract'],
    'data': [
        'security/ir.model.access.csv',
        'data/chatgpt_model_data.xml',
        'views/account_invoice.xml',
        'views/res_config_settings_views.xml'
    ],
    'installable': True,
    'auto_install': False,
    # 'application': True,
}
