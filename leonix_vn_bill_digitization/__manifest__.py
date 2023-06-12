{
    'name': 'leonix_vn_bill_digitization',
    'version': '1.0',
    'category': 'Custom',
    'summary': 'Module for digitizing bills XML',
    'author': 'Leonix',
    'license': 'AGPL-3',
    'website': 'https://leonix.vn',
    'depends': ['base', 'account', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/template_preview_xml.xml',
        'data/cron.xml',
        'views/account_invoice.xml',
        'wizard/preview_xml_wizard.xml',
    ],
    'assets': {
        'mail.assets_messaging': [
            'leonix_vn_bill_digitization/static/src/models/*.js',
        ],
        'mail.assets_discuss_public': [
            'leonix_vn_bill_digitization/static/src/components/*/*',
        ],
        'web.assets_backend': [
            'leonix_vn_bill_digitization/static/src/components/**/*',
            'leonix_vn_bill_digitization/static/src/css/template_css.css',
            'leonix_vn_bill_digitization/static/src/css/description_css.css',
        ],
        'web.assets_frontend': [
            'leonix_vn_bill_digitization/static/src/css/template_css.css',
            'leonix_vn_bill_digitization/static/src/css/description_css.css',
        ]
    },
    
    'installable': True,
    'auto_install': False, 
}
