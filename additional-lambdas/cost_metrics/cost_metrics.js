var AWS = require('aws-sdk');
var https = require('https');
var crypto = require('crypto');
var totalSearchStr = "Total for linked account";
var lineSearchStr = "LinkedLineItem";


/* Get access to GA consolidated bill account where the cost line item file stored  
 */
exports.handler = function(input, context) {
    var latestObj = [];
    var elk_endpoint = new AWS.Endpoint(input.endpoint);
    var bucket = input.bucket;
    AWS.config.region = input.region;
    var sts = new AWS.STS({apiVersion: '2011-06-15'});
    var temp_credentials = {};

    sts_params = {
        RoleArn: input.role_arn, /* required */
        RoleSessionName: "TotalCostLambda", /* required */
        DurationSeconds: 900, /* Minimum 900 seconds (15 minutes) */
        };

    sts.assumeRole(sts_params, function(err, data) {
        if (err) {
            console.log("Error assuming role: " + err, err.stack); // an error occurred
        }

        else {
            temp_credentials = data.Credentials; // successful response

            var s3 = new AWS.S3({
                apiVersion: '2006-03-01',
                region: input.region,
                accessKeyId: temp_credentials.AccessKeyId,
                secretAccessKey: temp_credentials.SecretAccessKey,
                sessionToken: temp_credentials.SessionToken
                });
            find_file_in_s3(s3);
        }
    });

/*
 * Find the last modified cost line item file and get metrics from s3 file.  Generate JSON output and then post the metrics to ElasticSearch
 */
function find_file_in_s3(s3) {

    s3.listObjects({Bucket: bucket}, function(err, data) {
      if (err) console.log(err, err.stack); // an error occurred
      else {
          timestamp = new Date();
          var re = new RegExp("-aws-billing-csv-");
          for (var i = 0; i < data.Contents.length; i++) {
            var name = data.Contents[i].Key;
            if (re.test(name)) {
                if (latestObj.length === 0) { latestObj.push(data.Contents[i]); }
                else {
                if (new Date(latestObj[0].LastModified).getTime() < new Date(data.Contents[i].LastModified).getTime()){
                    latestObj.pop();
                    latestObj.push(data.Contents[i]);
                    // console.log("latest: " + JSON.stringify(latestObj));
                }
            }
        }
    }


    s3.getObject({Bucket: bucket, Key: latestObj[0].Key}, function(err, data) {
        if (err) {
            console.log("Error getting object " + err);
            }
        else {
            var arrOut = [];
            var matchItem = [];
            var timeStamp = new Date();
            var json_data = ' ';
            arrOut = String(data.Body).split('\n');

            //  index name format: cwl-YYYY.MM.DD
            var indexName = [
                'cost-' + timeStamp.getUTCFullYear(),              // year
                ('0' + (timeStamp.getUTCMonth() + 1)).slice(-2),  // month
                ('0' + timeStamp.getUTCDate()).slice(-2)          // day
            ].join('.');

            var action = { "index": {} };
            action.index._index = indexName;
            action.index._type = "Cost";

            for (var i = 0; i < arrOut.length; i++) {
		var acItem = [];
		if (arrOut[i].indexOf(totalSearchStr) > -1) {
	           matchItem = String(arrOut[i]).substring(arrOut[i].indexOf(totalSearchStr)).split(',');
	           acItem.push({
		      "AccountName": matchItem[0].substring(40, matchItem[0].length-2),
		      "timestamp": new Date().toISOString(),
		      "AccountId": matchItem[0].substring(26, 38),
                      "TotalCost": parseFloat(matchItem[matchItem.length-1].replace(/"/g, '').replace(/\\/g, ''))
		   });
	         } else if (arrOut[i].indexOf(lineSearchStr) > -1) {
			    matchItem = String(arrOut[i]).split('","');
			    acItem.push({
				"AccountName": matchItem[9],
				"timestamp": new Date().toISOString(),
				"AccountId": matchItem[2],
				"ProductCode": matchItem[12],
				"ProductName": matchItem[13],
				"UsageType": matchItem[15],
				"LineItemCost": parseFloat(matchItem[matchItem.length-1].replace(/"/g, '').replace(/\\/g, ''))
		            });
		 }
		 if (acItem.length > 0) {
			json_data += [ JSON.stringify(action), JSON.stringify(acItem), ].join('\n') + '\n';
	         } 
                }
                json_data = json_data.replace(/\[/g, '').replace(/\]/g, '').replace(/\\/g, '');
                console.log("JSON OUTPUT " + json_data);
                postToES(json_data, elk_endpoint, AWS.config.region, context);
              }
          });

      }
    });
    }

 /*
 * Post json string to Elasticsearch
 */
function postToES(json_str, endpoint, region, context) {
    var req = new AWS.HttpRequest(endpoint);
    var creds = new AWS.EnvironmentCredentials('AWS');

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
            //console.log('Response: ' + respBody);
            context.succeed('sent json: ' + json_str);
        });
    }, function(err) {
        //console.log('Error: ' + err);
        context.fail('failed with error ' + err);
    });
    }

};
