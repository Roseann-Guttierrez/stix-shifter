from stix_shifter_utils.modules.base.stix_transmission.base_query_connector import BaseQueryConnector


class SecurityAdvisorQueryConnector(BaseQueryConnector):
    def __init__(self, host, auth):
        self.host = host
        self.auth = auth

    def create_query_connection(self, query):

        return_obj = {}
        return_obj['success'] = True
        return_obj['search_id'] = query

        return return_obj
