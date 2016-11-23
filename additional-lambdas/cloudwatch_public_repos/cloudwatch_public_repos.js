/*
{
  "endpoint": "search-gadevs-elk-o456g5esjx43hq3b6k5nokmjbm.ap-southeast-2.es.amazonaws.com",
  "index_prefix": "repo",
  "type": "PublicRepos"
}
*/
/* based on https://github.com/awslabs/amazon-elasticsearch-lambda-samples/blob/master/src/kinesis_lambda_es.js */

var AWS = require('aws-sdk');
var path = require('path');
var http = require('https');
var url = require('url');

/*
 * The AWS credentials are picked up from the environment.
 * They belong to the IAM role assigned to the Lambda function.
 * Since the ES requests are signed using these credentials,
 * make sure to apply a policy that allows ES domain operations
 * to the role.
 */
var creds = new AWS.EnvironmentCredentials('AWS');

/* Lambda "main": Execution begins here */
exports.lambda_handler = function(event, context) {
    var endpoint = new AWS.Endpoint(event.endpoint);
    var region = event.endpoint.split('.')[1];

    //  index name format: prefix-YYYY.MM.DD
    var timestamp = new Date();
    var index_name = [
        event.index_prefix + '-' + timestamp.getUTCFullYear(),  // year
        ('0' + (timestamp.getUTCMonth() + 1)).slice(-2),        // month
        ('0' + timestamp.getUTCDate()).slice(-2)                // day
    ].join('.');

    count_repos('/users/GeoscienceAustralia/repos', 0, function(count){
        var data = [{
            "index": {
                "_index": index_name,
                "_type": event.type
            }
        }, {}];
        data[1]['timestamp'] = new Date().toISOString();
        data[1][event.type] = count;
        data[1]['type'] = "github";
        data[1]['Type'] = "github";

        json_data = data.map(JSON.stringify).join('\n') + '\n';

        postToES(json_data, endpoint, region, context);
    });
}

function count_repos(path, count, callback) {

	var options = {
		host: 'api.github.com',
		path: path,
		headers: { 'User-Agent': 'ga-repo-counter' }  // github api requires user-agent
	};

	http.request(options, function(res) {
	   var body = '';
	   res.on('data', function(chunk) { body += chunk; });

	   res.on('end', function() {
	   	json = JSON.parse(body);
	   	count += json.length // # of repos = # elements in json

	   	// handle pagination recursively by getting next URL from link HTTP header
	   	links = parse_link_header(res.headers['link'])
	   	if ('next' in links) {
	   		count_repos(links['next'], count, callback)
	   	} else {
	   		callback(count);
	   	}
	   });
	}).end();

}

/*
 * Post json string to Elasticsearch
 */
function postToES(json_str, endpoint, region, context) {
    var req = new AWS.HttpRequest(endpoint);

    req.method = 'POST';
    req.path = '/_bulk';
    req.region = region;
    req.headers['presigned-expires'] = false;
    req.headers['Host'] = endpoint.host;
    req.body = json_str;

    var signer = new AWS.Signers.V4(req , 'es');  // es: service code
    signer.addAuthorization(creds, new Date());

    var send = new AWS.NodeHttpClient();
    send.handleRequest(req, null, function(httpResp) {
        var respBody = '';
        httpResp.on('data', function (chunk) {
            respBody += chunk;
        });
        httpResp.on('end', function (chunk) {
            console.log('Response: ' + respBody);
            context.succeed('sent json: ' + json_str);
        });
    }, function(err) {
        console.log('Error: ' + err);
        context.fail('failed with error ' + err);
    });
}

/*
 * parse_link_header()
 * https://gist.github.com/niallo/3109252
 *
 * Parse the Github Link HTTP header used for pageination
 * http://developer.github.com/v3/#pagination
 */
function parse_link_header(header) {
  if (header.length === 0) {
    throw new Error("input must not be of zero length");
  }

  // Split parts by comma
  var parts = header.split(',');
  var links = {};
  // Parse each part into a named link
  parts.forEach(function(p) {
    var section = p.split(';');
    if (section.length != 2) {
      throw new Error("section could not be split on ';'");
    }
    var url = section[0].replace(/<(.*)>/, '$1').trim();
    var name = section[1].replace(/rel="(.*)"/, '$1').trim();
    links[name] = url;
  });

  return links;
}