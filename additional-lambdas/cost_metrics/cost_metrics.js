var AWS = require('aws-sdk');
var TOTALSEARCHSTR = 'Total for linked account';
var LINESEARCHSTR = 'LinkedLineItem';


/* Get access to GA consolidated bill account where the cost line item file stored  
 */
exports.handler = function(input, context) {
    AWS.config.region = input.region;
    var sts = new AWS.STS({apiVersion: '2011-06-15'});
    var temp_credentials = {};

    var sts_params = {
        RoleArn: input.role_arn, /* required */
        RoleSessionName: 'TotalCostLambda', /* required */
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
        var bucket = input.bucket;
        var latestObj = [];
        var secondLatestObj = [];
        s3.listObjects({Bucket: bucket}, function(err, data) {
            if (err) console.log(err, err.stack); // an error occurred
            else {
                var re = new RegExp('-aws-billing-csv-');
                for (var i = 0; i < data.Contents.length; i++) {
                    var name = data.Contents[i].Key;
                    if (re.test(name)) {
                        if (latestObj.length === 0) { latestObj.push(data.Contents[i]); }
                        else {
                            if (new Date(latestObj[0].LastModified).getTime() < new Date(data.Contents[i].LastModified).getTime()){
                                if (secondLatestObj.length === 0) { secondLatestObj.push(latestObj[0]); }
                                else {
                                    secondLatestObj.pop();
                                    secondLatestObj.push(latestObj[0]);
                                }
                                latestObj.pop();
                                latestObj.push(data.Contents[i]);
                            }
                        }
                    }
                }
                
                /* AWS still update the previous months file for a few days at the start of a new month
                   The below chunk of code is to ensure that our 'latestObj' is correct for this month (to avoid a data skew) */
                var latestFileMonth = latestObj[0].Key.slice(-6).substr(0,2);
                var secondLatestFileMonth = secondLatestObj[0].Key.slice(-6).substr(0,2);
                var currMonth = ('0' + (new Date().getUTCMonth() + 1)).slice(-2);
                if (latestFileMonth !== currMonth) {
                    if (secondLatestFileMonth === currMonth) {
                        latestObj.pop();
                        latestObj.push(secondLatestObj[0]);
                    } else { console.log('There was an error finding the correct file for this month') }
                }
                
                s3.getObject({Bucket: bucket, Key: latestObj[0].Key}, function(err, data) {
                    if (err) console.log("Error getting object " + err); // an error occurred
                    else {
                        var arrOut = [];
                        var matchItem = [];
                        var timeStamp = new Date();
                        var json_data = ' ';
                        var elk_endpoint = new AWS.Endpoint(input.endpoint);
                        arrOut = String(data.Body).split('\n');

                        //  index name format: cost-YYYY.MM.DD
                        var indexName = [
                            'cost-' + timeStamp.getUTCFullYear(),              // year
                            ('0' + (timeStamp.getUTCMonth() + 1)).slice(-2),  // month
                            ('0' + timeStamp.getUTCDate()).slice(-2)          // day
                        ].join('.');

                        var action = { 'index': {} };
                        action.index._index = indexName;
                        action.index._type = 'Cost';

                        for (var i = 0; i < arrOut.length; i++) {
                            var acItem = [];
                            if (arrOut[i].indexOf(TOTALSEARCHSTR) > -1) {
                                matchItem = String(arrOut[i]).substring(arrOut[i].indexOf(TOTALSEARCHSTR)).split(',');
                                acItem.push({
                                    'AccountName': matchItem[0].substring(40, matchItem[0].length-2),
                                    'timestamp': new Date().toISOString(),
                                    'AccountId': matchItem[0].substring(26, 38),
                                    'TotalCost': parseFloat(matchItem[matchItem.length-1].replace(/"/g, '').replace(/\\/g, ''))
                                });
                            } else if (arrOut[i].indexOf(LINESEARCHSTR) > -1) {
                                matchItem = String(arrOut[i]).split('","');
                                acItem.push({
                                    'AccountName': matchItem[9],
                                    'timestamp': new Date().toISOString(),
                                    'AccountId': matchItem[2],
                                    'ProductCode': matchItem[12],
                                    'ProductName': matchItem[13],
                                    'UsageType': matchItem[15],
                                    'LineItemCost': parseFloat(matchItem[matchItem.length-1].replace(/"/g, '').replace(/\\/g, ''))
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
        req.headers.Host = endpoint.host;
        req.body = json_str;

        var signer = new AWS.Signers.V4(req , 'es');  // es: service code
        signer.addAuthorization(creds, new Date());

        var send = new AWS.NodeHttpClient();
        send.handleRequest(req, null, function(httpResp) {
            var respBody = '';
            httpResp.on('data', function (chunk) {
                respBody += chunk;
            });
            httpResp.on('end', function () {
                context.succeed('sent json: ' + json_str);
            });
        }, function(err) {
            context.fail('failed with error ' + err);
        });
    }
};
