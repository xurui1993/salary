"""Synthetic selectors for mocked unit tests, never an observed/live profile.

Do not copy these dictionaries into backend/*.profile.json. Production loaders
are deliberately unchanged and still require separately verified configuration.
"""


def order_profile():
    keys=('agency_context','city_trigger','city_popup','city_group','city_group_label',
          'city_confirm','city_close','content_frame','reset_button','query_button',
          'submit_button','date_trigger','date_option','start_input','end_input')
    return {**{key: f'[data-unit-control="{key}"]' for key in keys},
            'verified': False, 'test_only': True, 'dataset': 'issue_orders',
            'selection_mode': 'target_city', 'time_basis': 'tracking_finish',
            'all_city_riders': True, 'expected_agency_id': '31029436',
            'city_option': '[data-unit-city="{agency_id}"]',
            'city_selected_option': '[data-unit-selected-city="{agency_id}"]',
            'all_state_value':'all', 'all_label_value':'all'}


def rider_profile(plan):
    keys=('notice_dismiss_button','agency_context','city_trigger','city_popup',
          'city_group','city_group_label','city_confirm','city_close')
    return {**{key:f'[data-unit-control="{key}"]' for key in keys},
            'verified':False,'test_only':True,'expected_agency_id':plan.agency_id,
            'selection_mode':'target_city',
            'city_option':'[data-unit-city="{agency_id}"]',
            'city_selected_option':'[data-unit-selected-city="{agency_id}"]',
            'content_frame':'iframe[data-unit-frame="rider"]'}
