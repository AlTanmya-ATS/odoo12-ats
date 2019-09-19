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
    'version': '1',

    # any module necessary for this one to work correctly
    'depends': ['base',
                'account', 'hr'
                ],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'views/resources.xml',
        'wizard/asset_modify_view.xml',
        'views/form_views.xml',
        'views/inherited_form_view.xml',
        'views/views.xml',
        'views/menuitem_view.xml',
        'views/templates.xml',
        # 'views/res_config_setting.xml',
        'wizard/mas_entries.xml',
        'wizard/re_class.xml',
        'wizard/modify_dep.xml',
        'wizard/confirmation_view.xml',
        'wizard/add_source_line.xml'

    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
    'qweb': [
        'static/src/xml/*.xml',
    ],
}
