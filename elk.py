import boto3
import argparse
import json
import time
import requests
import zipfile
import re
import os


def create_elasticsearch_domain(name, account_id, boto_session, lambda_role, cidr):
    """
    Create Elastic Search Domain

    """

    boto_elasticsearch = boto_session.client('es')
    total_time = 0

    resource = "arn:aws:es:ap-southeast-2:{0}:domain/{1}/*".format(account_id, name)

    access_policy = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Principal": {"AWS": str(lambda_role)}, "Action": "es:*", "Resource": resource},
        {"Effect": "Allow", "Principal": {"AWS": "*"}, "Action": "es:*", "Resource": resource,
         "Condition": {"IpAddress": {"aws:SourceIp": "{0}".format(cidr)}}}
    ]}

    endpoint = None

    time.sleep(5)

    try:
        print('Creating elasticsearch domain: {0}'.format(name))
        boto_elasticsearch.create_elasticsearch_domain(
            DomainName=name,
            ElasticsearchVersion='2.3',
            ElasticsearchClusterConfig={
                'InstanceType': 't2.micro.elasticsearch',
                'InstanceCount': 1,
                'DedicatedMasterEnabled': False,
                'ZoneAwarenessEnabled': False
            },
            EBSOptions={
                'EBSEnabled': True,
                'VolumeType': 'gp2',
                'VolumeSize': 20
            }
        )
        time.sleep(10)

        attempts = 1
        while True:
            print('Trying to apply access policies to elasticsearch domain: {0} (attempt: {1})'.format(name, attempts))
            try:
                boto_elasticsearch.update_elasticsearch_domain_config(
                DomainName=name,
                AccessPolicies=json.dumps(access_policy)
                )
                break
            except Exception as e:
                attempts += 1
                if attempts > 3:
                    print('Failed to apply access policies. Please run this script again with `-a delete -n {0}`'
                          'and wait approx 20 minutes before trying again'.format(name))
                    print('Full error was: {0}'.format(e))
                    exit(1)
                else:
                    time.sleep(2)

    except Exception as e:
        print('Could not create elasticsearch domain: {0}.'.format(name))
        print('Error was: {0}'.format(e))
        exit(1)

    while True:
        try:
            es_status = boto_elasticsearch.describe_elasticsearch_domain(DomainName=name)
            processing = es_status['DomainStatus']['Processing']

            if not processing:
                endpoint = es_status['DomainStatus']['Endpoint']
                print('Domain: {0} has been created!'.format(name))
                break
            else:
                print('Domain: {0} is still processing. Waiting for 120 seconds before checking again'.format(name))
                time.sleep(120)

        except Exception:
            print('Domain: {0} is still processing. Waiting for 120 seconds before checking again'.format(name))
            total_time += 120
            if total_time > 1800:
                print('Script has been running for over 30 minutes... This likely means that your elastic search domain'
                      ' has not created successfully. Please check the Elasticsearch Service dashboard in AWS console'
                      ' and delete the domain named {0} if it exists before trying again'.format(name))
                exit(1)
            time.sleep(120)

    return endpoint


def configure_kibana(endpoint):
    """
    Configures kibana
    and Invokes the lambda function for the first time
    """

    for file in os.listdir('./template_mappings'):
        with open('./template_mappings/{0}'.format(file)) as data_file:
            data = json.load(data_file)
            template_name = data['template']
            index_pattern = {"title": template_name, "timeFieldName": "timestamp"}

            print('Deleting any non-formated events that have arrived for {0}'.format(template_name))
            requests.delete('https://{0}/{1}'.format(endpoint, template_name))

            print('Creating a data template to format data for: {0}'.format(template_name))
            requests.put('https://{0}/_template/{1}'.format(endpoint, template_name), data=json.dumps(data))

            print('Creating index-pattern called {0} to capture incoming metrics for that index'.format(template_name))
            requests.put('https://{0}/.kibana-4/index-pattern/{1}'.format(endpoint, template_name),
                         data=json.dumps(index_pattern))

    default_index = {
        "defaultIndex": "cw-*"
    }

    # The below doesn't appear to work for some reason.
    print('Designating cw-* as the default index pattern')
    requests.put('https://{0}/.kibana-4/config/4.1.2'.format(endpoint), data=json.dumps(default_index))

    print('Kibana has been configured!')


def create_lambda_functions(esname, endpoint, boto_session, role_arn):
    """
    Creates lambda functions and cloudwatch schedules to run those functions from directories in ./lambdas
    """

    # Wait for the IAM Role to be ready to attach
    boto_lambda = boto_session.client('lambda')
    region = endpoint.split('.')[1]
    runtime = handler = description = timeout = event_rule = schedule = None

    time.sleep(30)

    for folder in os.listdir('./lambdas'):
        try:
            with open('./lambdas/{0}/lambda_config.json'.format(folder)) as data_file:
                config = json.load(data_file)
                runtime = config['runtime']
                handler = config['handler']
                description = config['description']
                timeout = config['timeout']
                event_rule = config['cloudwatch_rule']
                schedule = config['schedule']

                if 'endpoint' in event_rule:
                    event_rule['endpoint'] = endpoint
                if 'region' in event_rule:
                    event_rule['region'] = region
                if 'domainname' in event_rule:
                    event_rule['domainname'] = esname

        except Exception as e:
            print("There is either no lambda_config.json file, or a missing config variable for {0}".format(folder))
            print("Error: {0}".format(e))
            exit(1)

        for file in os.listdir('./lambdas/{0}'.format(folder)):
            if file != 'lambda_config.json':
                file_details = file.split('.')

                zip_file = zipfile.ZipFile('{0}_{1}.zip'.format(esname, file_details[0]), 'w')
                zip_file.write('./lambdas/{0}/{1}'.format(folder, file), './{0}'.format(file))
                zip_file.close()

                print('Creating a lambda function: \'{0}_{1}\' using the local file \'{2}\''
                      .format(esname, folder, file))

                with open('{0}_{1}.zip'.format(esname, file_details[0]), 'rb') as zfile:
                    response = boto_lambda.create_function(
                        FunctionName='{0}_{1}'.format(esname, folder),
                        Runtime=runtime,
                        Role=role_arn,
                        Handler=handler,
                        Code={
                            'ZipFile': zfile.read()
                        },
                        Description=description,
                        Timeout=timeout
                    )

                lambda_arn = response['FunctionArn']

                print('Updating lambda permissions to allow events.amazonaws.com to invoke the function')

                boto_lambda.add_permission(
                    FunctionName=lambda_arn,
                    StatementId='0',
                    Action='lambda:InvokeFunction',
                    Principal='events.amazonaws.com'
                )

                boto_cloudwatch = boto_session.client('events')

                print('Creating a Cloudwatch rule \'{0}_{1}\''.format(esname, folder))
                boto_cloudwatch.put_rule(
                    Name='{0}_{1}'.format(esname, folder),
                    ScheduleExpression=schedule,
                    State='ENABLED',
                    Description='runs lambda function: {0}_{1} on schedule: {2}'.format(esname, folder, schedule)
                )

                print('Creating a target for the Cloudwatch rule, pointing it at the lambda function')
                boto_cloudwatch.put_targets(
                    Rule='{0}_{1}'.format(esname, folder),
                    Targets=[
                        {
                            'Id': '0',
                            'Arn': lambda_arn,
                            'Input': json.dumps(event_rule),
                        }
                    ]
                )

    print('Removing zip files that have been created during execution')

    for file in os.listdir('.'):
        if file.split('.')[-1] == 'zip':
            os.remove(file)


def create_lambda_iam_role(name, boto_session):
    """
    Creates IAM Policy and Role to attach to the lambda function to handle cloudwatch metrics

    """

    boto_iam = boto_session.client('iam')

    policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "ec2:DescribeInstances",
                    "ec2:DescribeVolumes",
                    "rds:DescribeDBInstances",
                    "sts:AssumeRole",
                    "cloudwatch:GetMetricStatistics",
                    "es:*",
                    "s3:*"
                ],
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                "Resource": "arn:aws:logs:*:*:*"
            }
        ]
    }

    assumerole_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "lambda.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }

    print('Creating IAM Policy \'{0}_processing_lambda_policy\' to enable access to cloudwatch metrics'.format(name))
    policy = boto_iam.create_policy(
        PolicyName='{0}_processing_lambda_policy'.format(name),
        PolicyDocument=json.dumps(policy_document),
        Description='Iam Policy created for elasticsearch domain \'{0}\' that should give access to process cloudwatch'
                    ' metrics to a lambda function'.format(name)
    )

    print('Creating IAM Role \'{0}_processing_lambda_role\' to apply to lambda function'.format(name))
    role = boto_iam.create_role(
        RoleName='{0}_processing_lambda_role'.format(name),
        AssumeRolePolicyDocument=json.dumps(assumerole_document)
    )

    print('Attaching IAM Policy to IAM Role to enable cloudwatch metrics access via the role')
    boto_iam.attach_role_policy(
        RoleName=role['Role']['RoleName'],
        PolicyArn=policy['Policy']['Arn']
    )

    return role['Role']['Arn']

def delete_elk(name, boto_session):
    """
    Deletes an elk environment with the specified name

    """
    for file in os.listdir('./lambdas'):
        del_name = '{0}_{1}'.format(name, file)

        # Delete Cloudwatch objects
        print('Deleting Cloudwatch rule: {0}'.format(del_name))
        try:
            boto_cloudwatch = boto_session.client('events')
            boto_cloudwatch.remove_targets(Rule=del_name, Ids=['0'])
            boto_cloudwatch.delete_rule(Name=del_name)
        except Exception as e:
            if 'ResourceNotFoundException' not in str(e):
                print(e)
            else:
                print('Cloudwatch rule {0} did not exist, going ahead with other deletions'.format(del_name))

        # Delete Lambda objects
        print('Deleting Lambda function: {0}'.format(del_name))
        try:
            boto_lambda = boto_session.client('lambda')
            boto_lambda.delete_function(FunctionName=del_name)
        except Exception as e:
            if 'ResourceNotFoundException' not in str(e):
                print(e)
            else:
                print('Lambda function {0} did not exist, going ahead with other deletions'.format(del_name))

    # Delete IAM objects
    role_name = '{0}_processing_lambda_role'.format(name)
    policy_name = '{0}_processing_lambda_policy'.format(name)

    policy_arn = 'NO POLICY FOUND IN SEARCH'

    try:
        boto_iam = boto_session.client('iam')

        for policy in boto_iam.list_policies()['Policies']:
            if policy['PolicyName'] == policy_name:
                policy_arn = policy['Arn']
    except Exception as e:
        print(e)

    print('Deleting iam objects: {0} and {1}'.format(role_name, policy_name))

    try:
        boto_iam = boto_session.client('iam')

        boto_iam.detach_role_policy(RoleName=role_name,
                                    PolicyArn=policy_arn)
        boto_iam.delete_role(RoleName=role_name)
        boto_iam.delete_policy(PolicyArn=policy_arn)
    except Exception as e:
        if 'ResourceNotFoundException' not in str(e) and 'NoSuchEntity' not in str(e):
            print(e)
        else:
            print('IAM Role {0} or IAM Policy {1} did not exist, going ahead with other deletions'.format(role_name, policy_name))

    # Delete elasticsearch domain object
    print('Deleting Elasticsearch domain: {0}'.format(name))
    try:
        boto_elasticsearch = boto_session.client('es')

        boto_elasticsearch.delete_elasticsearch_domain(DomainName=name)
    except Exception as e:
        if 'ResourceNotFoundException' not in str(e):
            print(e)
        else:
            print('Elasticsearch domain {0} did not exist'.format(name))

    print('All Eck objects for: \'{0}\' have been deleted'.format(name))

def parse_args():
    """
    Parses the command line arguments for use throughout the script
    :return:
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--profile',
                        default='default',
                        help='Which profile to use (from your aws credentials file. default: default')
    parser.add_argument('-n', '--name',
                        default='elk',
                        help='What name to give the elk instance. default: elk')
    parser.add_argument('-a', '--action',
                        default='create',
                        help='The action to perform. options: create, or delete. Delete will delete all elk '
                             'objects with the provided name (-n). default: create')

    return parser.parse_args()


def main():
    """
    Create Elastic Search Domain

    """

    args = parse_args()

    profile = args.profile
    domainname = args.name
    action = args.action.upper()
    regex_pattern = '^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])(\/([0-9]|[1-2][0-9]|3[0-2]))$'

    session = boto3.Session(profile_name=profile)

    sts = session.client('sts')
    account_id = sts.get_caller_identity()['Account']

    if action in ['CREATE']:
        cidr = input('Please provide a CIDR block to restrict access to elasticsearch domain: {0}\n'.format(domainname))
        if not re.match(regex_pattern, cidr):
            while True:
                print('The provided CIDR: \'{0}\' does not match a cidr pattern. eg. 0-255.0-255.0-255.0-255/0-32'.format(cidr))
                cidr = input('Please provide a working CIDR block\n')
                if re.match(regex_pattern, cidr):
                    break
                else:
                    continue
        role_arn = create_lambda_iam_role(domainname, session)
        endpoint = create_elasticsearch_domain(domainname, account_id, session, role_arn, cidr)
        create_lambda_functions(domainname, endpoint, session, role_arn)
        configure_kibana(endpoint)
        print('Kibana Endpoint: \'https://{0}/_plugin/kibana/\''.format(endpoint))
        print('elk {0} has been fully created'.format(domainname))
    elif action in ['UPDATE']:
        print('update placeholder hit.... No code to run yet! :)')
    elif action in ['DELETE']:
        user_input = input('Are you sure you want to delete the ELK stack with name {0}? '.format(domainname))
        if user_input.upper() in ['YES', 'Y']:
            delete_elk(domainname, session)
        else:
            print('No action performed. Exiting.')
    else:
        print('Unrecognised action specified, please set either CREATE or DELETE')

if __name__ == '__main__':
    main()
