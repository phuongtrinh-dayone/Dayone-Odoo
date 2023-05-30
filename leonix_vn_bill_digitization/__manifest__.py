{
    'name': 'leonix_vn_bill_digitization',
    'version': '1.0',
    'category': 'Custom',
    'summary': 'Module for digitizing bills XML',
    'author': 'Leonix',
    'website': 'https://leonix.vn',
    'depends' : ['base','account','account_invoice_extract'],
    'data': [
        'views/account_invoice.xml',
    ],
    'installable': True,
    'auto_install': False,
}
