# -*- coding: utf-8 -*-
{
    'name': "Mrp Report",

    'summary': """
     Adding attendance to tracks in Events """,

    'description': """
      adding attendance to each tracks in Event
        and note field to 'event.track' model ,
      add Status = withdraw to event.registration model   
    """,

    'author': "My Company",
    'website': "http://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/master/odoo/addons/base/module/module_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '1.1',

    # any module necessary for this one to work correctly
    'depends': ['base','mrp'],

    # always loaded
    'data': [
        # 'security/ir.model.access.csv',

        'report/manufacturing_orders.xml',
        'report/manufacturing_orders_action.xml'
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
}