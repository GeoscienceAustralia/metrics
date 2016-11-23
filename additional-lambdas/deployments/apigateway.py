# http://stackoverflow.com/questions/38027414/giving-aws-api-gateway-permission-to-invoke-lambda-function-using-boto3
import boto3
import json
import os

session = boto3.Session()
lmbda = session.client('lambda')
apigateway = session.client('apigateway')

def create_lambda(role):
	import zipfile
	zf = zipfile.ZipFile('deployment_lambda.zip', mode='w')
	zf.write('deployment.py')
	zf.close()

	with open('deployment_lambda.zip', 'rb') as zfile:
		response = lmbda.create_function(
			FunctionName='deployment_metrics_lambda',
			Runtime='python2.7',
			Role=role,
			Handler='deployment.lambda_handler',
			Code={
				'ZipFile': zfile.read()
			}
		)

	os.remove('deployment_lambda.zip')
	return response['FunctionArn']

def create_api_gateway(endpoint, lambda_arn):
	rest_api = apigateway.create_rest_api(
		name='deployment_metrics_apigateway'
	)

	root_id = apigateway.get_resources(
		restApiId=rest_api['id']
	)['items'][0]['id']

	api_method = apigateway.put_method(
		restApiId=rest_api['id'],
		resourceId=root_id,
		httpMethod='POST',
		authorizationType='NONE'
	)

	template = """{{
		"timestamp": $input.json('timestamp'),
		"Application": $input.json('Application'),
		"Environment": $input.json('Environment'),
		"endpoint": "{0}"
	}}""".format(endpoint)

	apigateway.put_integration(
		restApiId=rest_api['id'],
		resourceId=root_id,
		httpMethod='POST',
		type='AWS',
		requestTemplates={
			'application/json': template
		},
		integrationHttpMethod='POST',
		uri='arn:aws:apigateway:ap-southeast-2:lambda:path/2015-03-31/functions/{}/invocations'.format(lambda_arn)
	)

	apigateway.put_method_response(
	    restApiId=rest_api['id'],
	    resourceId=root_id,
	    httpMethod='POST',
	    statusCode='200',
	    responseModels={
	        'application/json': 'Empty'
	    }
	)

	apigateway.put_integration_response(
	    restApiId=rest_api['id'],
	    resourceId=root_id,
	    httpMethod='POST',
	    statusCode='200',
	    responseTemplates={
	        'application/json': ''
	    }
	)

	apigateway.create_deployment(
	    restApiId=rest_api['id'],
	    stageName='prod'
	)

	lmbda.add_permission(
	    FunctionName=lambda_arn,
	    StatementId='apigateway-deployment-metrics-lambda',
	    Action='lambda:InvokeFunction',
	    Principal='apigateway.amazonaws.com'
	    # SourceArn=self.create_api_permission_uri(api_resource)
	)

	return rest_api['id']

# def delete_lambda():
# 	lmbda.delete_function(FunctionName='deployment_metrics_lambda')

# def delete_api_gateway():
# 	apigateway.delete_rest_api(
# 		name='deployment_metrics_apigateway'
# 	)

# 	root_id = apigateway.get_resources(
# 		restApiId=rest_api['id']
# 	)['items'][0]['id']


def parse_args():
	"""
	Parses the command line arguments for use throughout the script
	:return:
	"""
	import argparse
	parser = argparse.ArgumentParser()
	parser.add_argument('-r', '--role',
	                  help='ARN for the role to run lambda with', required=True)
	parser.add_argument('-e', '--endpoint',
							help='Endpoint for ElasticSearch', required=True)
	parser.add_argument('-d', '--delete',
							help='Delete lambda and API Gateway', default=False)
	return parser.parse_args()


def main():
	args = parse_args()

	# TODO: Methods to delete lambda & api gateway
	# if args.delete:
	# 	delete_lambda()
	# 	delete_api_gateway()
	# 	print('Deleted')
	# 	exit()

	lambda_arn = create_lambda(args.role)
	api_id = create_api_gateway(args.endpoint, lambda_arn)

	url = 'https://' + api_id + '.execute-api.ap-southeast-2.amazonaws.com/prod'
	print('API Gateway endpoint: ' + url)
	print('\nExample invocation: curl -H "Content-Type: application/json" -X POST '
			'-d \'{"timestamp": "2016-10-26T02:56:47.158Z", "Application": "APPNAME",'
			' "Environment": "ENV"}\' ' + url)

if __name__ == '__main__':
    main()
