from __future__ import print_function
import boto3
import urllib2
import datetime
import json
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


def transform_data(data):
    """
    :param data:
    :return:
    """

    now = datetime.datetime.utcnow()
    iso_now = now.strftime('%Y-%m-%dT%H:%M:%S.{0}Z'.format(
        int(round(now.microsecond/1000.0))))
    index_name = now.strftime('deployment-%Y.%m.%d')

    structure = [{
      "index": {
        "_index": index_name,
        "_type": "deployment"
      }
    }, {
      "timestamp": data['timestamp'],
      "Application": data['Application'],
      "Environment": data['Environment'],
      "deployment": 1
    }]

    return '\n'.join(map(json.dumps, structure)) + '\n'


def make_request(endpoint, data, method='GET'):
    """
    This function handles a HTTP request to a given elasticsearch domain endpoint and method.
    :param endpoint: The elasticsearch domain endpoint
    :param data:
    :param method: the type of HTTP method to use. eg: 'GET POST DELETE etc'
    :return: The response of the request
    """

    host = endpoint
    endpoint = '{0}/_bulk'.format(host)
    region = endpoint.split('.')[1]
    service = endpoint.split('.')[2]
    credentials = boto3.session.Session().get_credentials()
    request = AWSRequest(method=method, url='https://{0}'.format(endpoint), data=data)
    SigV4Auth(credentials, service, region).add_auth(request)
    headers = dict(request.headers.items())
    opener = urllib2.build_opener(urllib2.HTTPHandler)
    request = urllib2.Request('https://{0}'.format(endpoint), request.data)

    request.add_header('Host', host)
    request.add_header('Content-Type', 'application/json')
    request.add_header('X-Amz-Date', headers['X-Amz-Date'])
    request.add_header('X-Amz-Security-Token', headers['X-Amz-Security-Token'])
    request.add_header('Authorization', headers['Authorization'])
    request.get_method = lambda: method

    print(request.data)

    return opener.open(request).read()


def lambda_handler(event, context):
    """
    This function acts as the entry point for lambda.
    :param event: AWS Lambda uses this parameter to pass in event data (eg. input) to the handler.
    :param context: AWS Lambda uses this parameter to provide runtime information to your handler.
    Context: https://docs.aws.amazon.com/lambda/latest/dg/python-context-object.html
    """
    transformed_data = transform_data(event)
    response = make_request(event['endpoint'], transformed_data, method='POST')
    return response