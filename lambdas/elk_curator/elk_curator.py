from __future__ import print_function
import boto3
import urllib2
import re
import datetime
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import cStringIO


def run_curator(name):
    """
    Cleans out any indices older than 30 days from the elasticsearch domain with the provided name
    :param name: the name of the elasticsearch domain to curate.
    """

    boto_elasticsearch = boto3.client('es')

    es_status = None

    try:
        es_status = boto_elasticsearch.describe_elasticsearch_domain(DomainName=name)
    except Exception as e:
        print('elastic search domain "{0}" does not appear to exist'.format(name))
        exit(1)

    endpoint = es_status['DomainStatus']['Endpoint']

    table_of_data = make_request('{0}/_cat/indices?v'.format(endpoint))

    list_of_indices = []
    deleted_indices = []

    indices = cStringIO.StringIO(table_of_data)
    for line in indices:
        line_list = line.strip().split()
        list_of_indices.append(line_list[2])

    today = datetime.datetime.now()

    print('Today: {0}'.format(today.strftime('%Y-%m-%d')))
    print('Indices found: {0}'.format(', '.join(list_of_indices)))

    regex = '(\d{4})[.](\d{1,2})[.](\d{1,2})$'
    for index in list_of_indices:
        if re.search(regex, index):
            parsed_index_date = '.'.join(re.findall(regex, index)[0][:3])
            index_date = datetime.datetime.strptime(parsed_index_date, '%Y.%m.%d')
            delta = today - index_date
            if delta.days > 30:
                deleted_indices.append(index)
                make_request('{0}/{1}'.format(endpoint, index), 'DELETE')

    if deleted_indices:
        print('Found and deleted the following old indices: {0}'.format(', '.join(deleted_indices)))


def make_request(endpoint, method='GET'):
    """
    This function handles a HTTP request to a given elasticsearch domain endpoint and method.
    :param endpoint: The elasticsearch domain endpoint
    :param method: the type of HTTP method to use. eg: 'GET POST DELETE etc'
    :return: The response of the request
    """

    region = endpoint.split('.')[1]
    service = endpoint.split('.')[2]
    credentials = boto3.session.Session().get_credentials()
    request = AWSRequest(method=method, url='https://{0}'.format(endpoint))
    SigV4Auth(credentials, service, region).add_auth(request)
    headers = dict(request.headers.items())
    opener = urllib2.build_opener(urllib2.HTTPHandler)
    request = urllib2.Request('https://{0}'.format(endpoint))

    request.add_header('X-Amz-Date', headers['X-Amz-Date'])
    request.add_header('X-Amz-Security-Token', headers['X-Amz-Security-Token'])
    request.add_header('Authorization', headers['Authorization'])
    request.get_method = lambda: method

    return opener.open(request).read()


def lambda_handler(event, context):
    """
    This function acts as the entry point for lambda.
    :param event: AWS Lambda uses this parameter to pass in event data (eg. input) to the handler.
    :param context: AWS Lambda uses this parameter to provide runtime information to your handler.
    Context: https://docs.aws.amazon.com/lambda/latest/dg/python-context-object.html
    """
    run_curator(event['domainname'])