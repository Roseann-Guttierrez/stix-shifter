import importlib
from stix_shifter.stix_translation.src.patterns.parser import generate_query
from stix2patterns.validator import run_validator
from stix_shifter.stix_translation.src.utils.stix_pattern_parser import parse_stix
import re
from ..utils.error_response import ErrorResponder
from .src.utils.exceptions import DataMappingException, StixValidationException, UnsupportedDataSourceException, TranslationResultException
from stix_shifter.stix_translation.src.modules.cim import cim_data_mapping
from stix_shifter.stix_translation.src.modules.car import car_data_mapping
from stix_shifter.stix_translation.src.utils.unmapped_attribute_stripper import strip_unmapped_attributes
from stix_shifter.stix_translation.src.utils.exceptions import DataMappingException
import sys
import glob
from os import path

TRANSLATION_MODULES = ['qradar', 'dummy', 'car', 'cim', 'splunk', 'elastic', 'bigfix', 'csa', 'csa:at', 'csa:nf', 'aws_security_hub', 'carbonblack',
                       'elastic_ecs', 'proxy', 'stix_bundle', 'msatp', 'security_advisor', 'guardium', 'aws_cloud_watch_logs']

RESULTS = 'results'
QUERY = 'query'
PARSE = 'parse'
SUPPORTED_ATTRIBUTES = "supported_attributes"
DEFAULT_LIMIT = 10000
DEFAULT_TIMERANGE = 5
START_STOP_PATTERN = "\s?START\s?t'\d{4}(-\d{2}){2}T\d{2}(:\d{2}){2}(\.\d+)?Z'\sSTOP\s?t'\d{4}(-\d{2}){2}T(\d{2}:){2}\d{2}.\d{1,3}Z'\s?"
SHARED_DATA_MAPPERS = {'elastic': car_data_mapping, 'splunk': cim_data_mapping, 'cim': cim_data_mapping, 'car': car_data_mapping}


class StixTranslation:
    """
    StixShifter class - implements translations of stix data
    """

    def __init__(self):
        self.args = []

    def _validate_pattern(self, pattern):
        errors = []
        # Temporary work around since pattern validator currently treats multiple qualifiers of the same type as invalid.
        start_stop_count = len(re.findall(START_STOP_PATTERN, pattern))
        if(start_stop_count > 1):
            pattern = re.sub(START_STOP_PATTERN, " ", pattern)
        errors = run_validator(pattern, stix_version='2.1')
        if (errors):
            raise StixValidationException("The STIX pattern has the following errors: {}".format(errors))

    def translate(self, module, translate_type, data_source, data, options={}, recursion_limit=1000):
        """
        Translated queries to a specified format
        :param module: What module to use
        :type module: one of TRANSLATION_MODULES 'qradar', 'dummy'
        :param translate_type: translation of a query or result set must be either 'results' or 'query'
        :type translate_type: str
        :param data: the data to translate
        :type data: str
        :param options: translation options { stix_validator: bool }
        :type options: dict
        :param recursion_limit: maximum depth of Python interpreter stack
        :type recursion_limit: int
        :return: translated results
        :rtype: str
        """
        dialect = None
        mod_dia = module.split(':', 1)
        module = mod_dia[0]
        if len(mod_dia) > 1:
            dialect = mod_dia[1]

        try:
            if module not in TRANSLATION_MODULES:
                raise UnsupportedDataSourceException("{} is an unsupported data source.".format(module))

            translator_module = importlib.import_module(
                "stix_shifter.stix_translation.src.modules." + module + "." + module + "_translator")

            if dialect is not None:
                interface = translator_module.Translator(dialect=dialect)
                options['dialect'] = dialect
            else:
                interface = translator_module.Translator()

            if translate_type == QUERY or translate_type == PARSE:
                # Increase the python recursion limit to allow ANTLR to parse large patterns
                current_recursion_limit = sys.getrecursionlimit()
                if current_recursion_limit < recursion_limit:
                    print("Changing Python recursion limit from {} to {}".format(current_recursion_limit, recursion_limit))
                    sys.setrecursionlimit(recursion_limit)
                options['result_limit'] = options.get('resultSizeLimit', DEFAULT_LIMIT)
                options['timerange'] = options.get('timeRange', DEFAULT_TIMERANGE)

                if translate_type == QUERY:
                    MAPPING_ERROR = "Unable to map the following STIX objects and properties to data source fields:"
                    # Carbon Black combined the mapping files into one JSON using process and binary keys.
                    # The query constructor has some logic around which of the two are used.
                    SKIP_MODULES_FROM_MAP_LOOKUP = ['csa', 'csa:at', 'csa:nf', 'carbonblack', 'car', 'cim', 'elastic']
                    if options.get('validate_pattern'):
                        self._validate_pattern(data)
                    queries = []
                    unmapped_stix_objects = {}
                    from_stix_mapping_files = self._fetch_from_stix_mapping_files(module)
                    if from_stix_mapping_files and not (module in SKIP_MODULES_FROM_MAP_LOOKUP):
                        for mapping_file in from_stix_mapping_files:
                            antlr_parsing = generate_query(data)
                            options['mapping_file'] = mapping_file
                            data_model_mapper = self._build_data_mapper(module, options)
                            if data_model_mapper:
                                stripped_parsing = strip_unmapped_attributes(antlr_parsing, data_model_mapper)
                                antlr_parsing = stripped_parsing.get('parsing')
                                unmapped_stix = stripped_parsing.get('unmapped_stix')
                                if unmapped_stix:
                                    unmapped_stix_objects[mapping_file] = unmapped_stix
                                if not antlr_parsing:
                                    continue
                                translated_queries = interface.transform_query(data, antlr_parsing, data_model_mapper, options)
                                # Will not work if the query constructor doesn't return an array of values. Need to enforce that each data source, even bundle, does this
                                if type(translated_queries == list):
                                    for query in translated_queries:
                                        queries.append(query)
                                else:
                                    queries = translated_queries
                        if not queries:
                            raise DataMappingException(
                                "{} {}".format(MAPPING_ERROR, unmapped_stix_objects)
                            )
                    else:
                        antlr_parsing = generate_query(data)
                        data_model_mapper = self._build_data_mapper(module, options)
                        if data_model_mapper:
                            stripped_parsing = strip_unmapped_attributes(antlr_parsing, data_model_mapper)
                            antlr_parsing = stripped_parsing.get('parsing')
                            unmapped_stix = stripped_parsing.get('unmapped_stix')
                            if not antlr_parsing:
                                raise DataMappingException(
                                    "{} {}".format(MAPPING_ERROR, unmapped_stix)
                                )
                        translated_queries = interface.transform_query(data, antlr_parsing, data_model_mapper, options)
                        queries = translated_queries
                    if not queries:
                        raise DataMappingException(
                            "{} {}".format(MAPPING_ERROR, unmapped_stix)
                        )
                    return {'queries': queries}
                else:
                    self._validate_pattern(data)
                    antlr_parsing = generate_query(data)
                    # Extract pattern elements into parsed stix object
                    parsed_stix_dictionary = parse_stix(antlr_parsing, options['timerange'])
                    parsed_stix = parsed_stix_dictionary['parsed_stix']
                    start_time = parsed_stix_dictionary['start_time']
                    end_time = parsed_stix_dictionary['end_time']
                    return {'parsed_stix': parsed_stix, 'start_time': start_time, 'end_time': end_time}

            elif translate_type == RESULTS:
                # Converting data from the datasource to STIX objects
                try:
                    return interface.translate_results(data_source, data, options)
                except Exception:
                    raise TranslationResultException()
            elif translate_type == SUPPORTED_ATTRIBUTES:
                # Return mapped STIX attributes supported by the data source
                data_model_mapper = self._build_data_mapper(module, options)
                mapped_attributes = data_model_mapper.map_data
                return {'supported_attributes': mapped_attributes}
            else:
                raise NotImplementedError('wrong parameter: ' + translate_type)
        except Exception as ex:
            print('Caught exception: ' + str(ex) + " " + str(type(ex)))
            response = dict()
            ErrorResponder.fill_error(response, message_struct={'exception': ex})
            return response

    def _fetch_from_stix_mapping_files(self, module):
        basepath = "/Users/danny.elliott.ibm.com/Documents/dev/stix-shifter/stix_shifter/stix_translation/src/modules/{}/json".format(module)
        mapping_paths = glob.glob(path.abspath(path.join(basepath, "*from_stix*.json")))
        mapping_files = []
        for map_path in mapping_paths:
            mapping_files.append(re.sub('^/', '', re.sub(basepath, '', map_path)))
        return mapping_files

    def _build_data_mapper(self, module, options):
        try:
            print("getting data model for {}".format(module))
            data_model = importlib.import_module("stix_shifter.stix_translation.src.modules." + module + ".data_mapping")
            return data_model.DataMapper(options)
        except Exception as ex:
            # Attempt to use the CIM or CAR mapper
            if options.get('data_mapper'):
                return SHARED_DATA_MAPPERS[options.get('data_mapper')].mapper_class(options)
            elif module in SHARED_DATA_MAPPERS:
                return SHARED_DATA_MAPPERS[module].mapper_class(options)
            else:
                return None
