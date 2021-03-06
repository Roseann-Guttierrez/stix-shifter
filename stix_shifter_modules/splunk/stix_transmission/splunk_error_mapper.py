from stix_shifter_utils.utils.error_mapper_base import ErrorMapperBase
from stix_shifter_utils.utils.error_response import ErrorCode

error_mapping = {
        'Unknown sid.': ErrorCode.TRANSMISSION_SEARCH_DOES_NOT_EXISTS,
        'Unable to parse the search': ErrorCode.TRANSMISSION_QUERY_PARSING_ERROR
    }

class ErrorMapper():

    DEFAULT_ERROR = ErrorCode.TRANSMISSION_MODULE_DEFAULT_ERROR

    @staticmethod
    def set_error_code(json_data, return_obj):
        message_text = None
        try:
            message_text = json_data['messages'][0]['text']
        except Exception as e:
            print("failed to find the message_0_text in: " + str(json_data))
            raise e
        
        error_code = ErrorMapper.DEFAULT_ERROR
        print('error code message: ' + message_text)

        for k,v in error_mapping.items():
            if k in message_text:
                error_code = v
                break
        
        if error_code == ErrorMapper.DEFAULT_ERROR:
            print("failed to map: "+ str(json_data))

        ErrorMapperBase.set_error_code(return_obj, error_code)
