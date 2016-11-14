from __future__ import print_function
import boto3
import urllib2
import datetime
import json
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


def get_other_metrics(input_dict):
    """

    :param input_dict:
    :return:
    """

    metricgroups = input_dict['metrics']
    pulled_data = []

    for namespace in metricgroups.keys():
        metrics = metricgroups[namespace]
        pulled_data.append(get_metrics(namespace, metrics, input_dict))

    transformed_data = transform_data(pulled_data)
    make_request(input_dict['endpoint'], transformed_data, method='POST')


def get_metrics(namespace, metrics, input_dict):
    """

    :param namespace:
    :param metrics:
    :param input_dict:
    :return:
    """
    cw_client = boto3.client('cloudwatch')
    responses = {}

    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(minutes=20)
    period = 300

    if namespace == 'AWS/RDS':
        db_client = boto3.client('rds')
        for db in db_client.describe_db_instances()['DBInstances']:
            dimensions = [{"Name": "DBInstanceIdentifier",
                           "Value": db['DBInstanceIdentifier']}]
            for metric in metrics:
                info = cw_client.get_metric_statistics(
                    Namespace=namespace,
                    MetricName=metric,
                    StartTime=start,
                    EndTime=end,
                    Period=period,
                    Statistics=[input_dict['measurement']],
                    Dimensions=dimensions
                )
                if info['Datapoints']:
                    responses.setdefault(db['DBInstanceIdentifier'], []).append({
                        'metric': metric,
                        'value': info['Datapoints'][-1][input_dict['measurement']],
                        'unit': info['Datapoints'][-1]['Unit'],
                        'database_id': db['DBInstanceIdentifier']
                    })

    if namespace == 'AWS/EBS':
        ebs_client = boto3.client('ec2')
        for vol in ebs_client.describe_volumes()['Volumes']:
            dimensions = [{"Name": "VolumeId",
                           "Value": vol['VolumeId']
                           }]
            for metric in metrics:
                info = cw_client.get_metric_statistics(
                    Namespace=namespace,
                    MetricName=metric,
                    StartTime=start,
                    EndTime=end,
                    Period=period,
                    Statistics=[input_dict['measurement']],
                    Dimensions=dimensions
                )
                if info['Datapoints']:
                    responses.setdefault(vol['VolumeId'], []).append({
                        'metric': metric,
                        'value': info['Datapoints'][-1][input_dict['measurement']],
                        'unit': info['Datapoints'][-1]['Unit'],
                        'volume_id': vol['VolumeId']
                    })

    return responses


def transform_data(data):
    """

    :param data:
    :return:
    """

    now = datetime.datetime.utcnow()
    iso_now = now.strftime('%Y-%m-%dT%H:%M:%S.{0}Z'.format(
        int(round(now.microsecond/1000.0))))
    index_name = now.strftime('cw-%Y.%m.%d')
    return_data = ''

    action = {'index': {}}
    action['index']['_index'] = index_name

    source = {}
    source['timestamp'] = iso_now

    for object in data:
        for key in object:
            for data_dict in object[key]:
                action['index']['_type'] = data_dict['metric']
                return_data += '{0}\n'.format(json.dumps(action))

                if 'volume_id' in data_dict:
                    source['volume_id'] = data_dict['volume_id']
                elif 'database_id' in data_dict:
                    source['database_id'] = data_dict['database_id']

                source[data_dict['metric']] = data_dict['value']
                source['unit'] = data_dict['unit']
                return_data += '{0}\n'.format(json.dumps(source))

                del source[data_dict['metric']]
                if 'volume_id' in source:
                    del source['volume_id']
                if 'database_id' in source:
                    del source['database_id']

    return return_data


def make_request(endpoint, data, method='GET'):
    """
    This function handles a HTTP request to a given elasticsearch domain endpoint and method.
    :param endpoint: The elasticsearch domain endpoint
    :param data: The data to send along with the request
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
    get_other_metrics(event)
