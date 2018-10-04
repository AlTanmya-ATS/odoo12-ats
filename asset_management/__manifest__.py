# -*- coding: utf-8 -*-
{
    'name': "ATS Asset Management",

    'summary': """
        Short (1 phrase/line) summary of the module's purpose, used as
        subtitle on modules listing or apps.openerp.com""",

    'description': """
        Long description of module's purpose
    """,

    'author': "My Company",
    'website': "http://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/master/odoo/addons/base/module/module_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base',
               'account' ,'hr','stock'
                ],

    # always loaded
    'data': [
        # 'security/ir.model.access.csv',
        'views/resources.xml',
        'wizard/asset_modify_view.xml',
        'views/views.xml',
        'views/templates.xml',
        'wizard/mas_entries.xml',
        'wizard/re_class.xml',
        'wizard/modify_dep.xml',
        'wizard/confirmation_view.xml'

    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
}