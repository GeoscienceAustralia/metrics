/* Script based on Amazon cloudwatch_logs.js and adapted by Jirotech
 * for exporting metrics from Cloudwatch to Amazon ES
*/

// v1.1.2
var https = require('https');
//var zlib = require('zlib');
var crypto = require('crypto');
var AWS = require("aws-sdk");
var extend = require('util')._extend;

var cloudwatch;
var ec2;


exports.handler = function(input, context) {
    var tags = [];
    var instanceids = {};
    cloudwatch = new AWS.CloudWatch({region: input.region});
    ec2 = new AWS.EC2({region: input.region});
    
    if (input.tag !== undefined) {
        tags =
            [{
                Name: 'tag:'+input.tag.name,
                Values: input.tag.values
            }];
            
    }
    
    state = 
        [{
                Name: "instance-state-name",
                Values: [ "running" ]
        }];
        
    filters = 
        {
            "Filters": state.concat(tags)
        };
        
    if (input.instances !== undefined) {
        instanceids = {
            InstanceIds: input.instances
        };
    }
    
    ec2.describeInstances(extend(filters,instanceids), function(err, data) {
        instances = [];
        if (data !== null) {
            data.Reservations.forEach(function(reservation) {
                reservation.Instances.forEach(function(instance){
                    instances.push(instance);
                });       
            });
        }
        transform(input.metrics, input.aggtime, input.measurement, instances, function(elasticsearchBulkData) {
            // post documents to the Amazon Elasticsearch Service
            post(input.endpoint, elasticsearchBulkData, function(error, success, statusCode, failedItems) {
                console.log('Response: ' + JSON.stringify({ 
                    "statusCode": statusCode 
                }));
    
                if (error) { 
                    console.log('Error: ' + JSON.stringify(error, null, 2));
        
                    if (failedItems && failedItems.length > 0) {
                        console.log("Failed Items: " +
                            JSON.stringify(failedItems, null, 2));
                    }

                    context.fail(JSON.stringify(error));
                
                } else {
                    console.log('Success: ' + JSON.stringify(success));
                    context.succeed('Success');
                }
            });
        });
        
    });
};

function transform(metrics, aggtime, measurement, instances , callback) {
    
    var itemsProcessed = 0;
    var requestBody = '';
    instances.forEach(function(instance) {
        metrics.forEach(function(metric) {
            getCloudWatchMetric(metric, aggtime, measurement, instance, function(cw_value){
                var source = {};
                var timestamp = new Date();

                //  index name format: cwl-YYYY.MM.DD
                var indexName = [
                    'cw-' + timestamp.getUTCFullYear(),              // year
                    ('0' + (timestamp.getUTCMonth() + 1)).slice(-2),  // month
                    ('0' + timestamp.getUTCDate()).slice(-2)          // day
                ].join('.');

                source.timestamp = new Date().toISOString();
                source.instance = instance.InstanceId;
                source.account = instance.NetworkInterfaces[0].OwnerId;
                source.instanceType = instance.InstanceType;
                source.instanceZone = instance.Placement.AvailabilityZone;
                source[metric] = cw_value.value;
                source.unit = cw_value.unit;
                
                console.log(source);
                
                var action = { "index": {} };
                action.index._index = indexName;
                action.index._type = metric;

                requestBody += [
                    JSON.stringify(action), 
                    JSON.stringify(source),
                ].join('\n') + '\n';
                itemsProcessed++;
            
                if(itemsProcessed === instances.length * metrics.length) {
                    callback(requestBody);
                }
            });
        });
    });
  
}

function post(endpoint, body, callback) {
    var requestParams = buildRequest(endpoint, body);
    
    var request = https.request(requestParams, function(response) {
        var responseBody = '';
        response.on('data', function(chunk) {
            responseBody += chunk;
        });
        response.on('end', function() {
            var info = JSON.parse(responseBody);
            var failedItems;
            var success;
            
            if (response.statusCode >= 200 && response.statusCode < 299) {
                failedItems = info.items.filter(function(x) {
                    return x.status >= 300;
                });

                success = { 
                    "attemptedItems": info.items.length,
                    "successfulItems": info.items.length - failedItems.length,
                    "failedItems": failedItems.length
                };
            }

            var error = response.statusCode !== 200 || info.errors === true ? {
                "statusCode": response.statusCode,
                "responseBody": responseBody
            } : null;

            callback(error, success, response.statusCode, failedItems);
        });
    }).on('error', function(e) {
        callback(e);
    });
    request.end(requestParams.body);
}

function buildRequest(endpoint, body) {
    var endpointParts = endpoint.match(/^([^\.]+)\.?([^\.]*)\.?([^\.]*)\.amazonaws\.com$/);
    var region = endpointParts[2];
    var service = endpointParts[3];
    var datetime = (new Date()).toISOString().replace(/[:\-]|\.\d{3}/g, '');
    var date = datetime.substr(0, 8);
    var kDate = hmac('AWS4' + process.env.AWS_SECRET_ACCESS_KEY, date);
    var kRegion = hmac(kDate, region);
    var kService = hmac(kRegion, service);
    var kSigning = hmac(kService, 'aws4_request');
    
    var request = {
        host: endpoint,
        method: 'POST',
        path: '/_bulk',
        body: body,
        headers: { 
            'Content-Type': 'application/json',
            'Host': endpoint,
            'Content-Length': Buffer.byteLength(body),
            'X-Amz-Security-Token': process.env.AWS_SESSION_TOKEN,
            'X-Amz-Date': datetime
        }
    };

    var canonicalHeaders = Object.keys(request.headers)
        .sort(function(a, b) { return a.toLowerCase() < b.toLowerCase() ? -1 : 1; })
        .map(function(k) { return k.toLowerCase() + ':' + request.headers[k]; })
        .join('\n');

    var signedHeaders = Object.keys(request.headers)
        .map(function(k) { return k.toLowerCase(); })
        .sort()
        .join(';');

    var canonicalString = [
        request.method,
        request.path, '',
        canonicalHeaders, '',
        signedHeaders,
        hash(request.body, 'hex'),
    ].join('\n');

    var credentialString = [ date, region, service, 'aws4_request' ].join('/');

    var stringToSign = [
        'AWS4-HMAC-SHA256',
        datetime,
        credentialString,
        hash(canonicalString, 'hex')
    ] .join('\n');

    request.headers.Authorization = [
        'AWS4-HMAC-SHA256 Credential=' + process.env.AWS_ACCESS_KEY_ID + '/' + credentialString,
        'SignedHeaders=' + signedHeaders,
        'Signature=' + hmac(kSigning, stringToSign, 'hex')
    ].join(', ');

    return request;
}

function hmac(key, str, encoding) {
    return crypto.createHmac('sha256', key).update(str, 'utf8').digest(encoding);
}

function hash(str, encoding) {
    return crypto.createHash('sha256').update(str, 'utf8').digest(encoding);
}


function getCloudWatchMetric(metric, aggtime, stattype, instance, callback) {
   var namespace = 'AWS/EC2'
   var dimensions = [
            {
            Name: 'InstanceId',
            Value: instance.InstanceId
            },
        ]
   if (['DiskSpaceUtilization', 'MemoryUtilization'].indexOf(metric) >= 0) {
    var namespace ='System/Linux'
    if (metric==='DiskSpaceUtilization'){
       dimensions = [
            {
            Name: 'InstanceId',
            Value: instance.InstanceId
            },
            {
            Name: 'Filesystem',
            Value: '/dev/xvda1'
            },
            {
            Name: 'MountPath',
            Value: '/'
            }
        ]
    }
   }
   var params = {
        MetricName: metric,
        Namespace: namespace, 
        Period: aggtime*60, 
        StartTime: new Date(new Date().getTime() - 4*(aggtime*60000)),
        EndTime: new Date(),
        Statistics: [
            stattype
        ],
        Dimensions: dimensions
    };
    
    cloudwatch.getMetricStatistics(params, function(err, data) {
        cw_value = {"value": null, "unit": null};
        if (err) {
            console.log(err, err.stack); // an error occurred
            
        }
        else if (data.Datapoints.length > 0) {
            cw_value = { "value": data.Datapoints.slice(-1)[0][stattype], "unit": data.Datapoints.slice(-1)[0]["Unit"] } ;
        }
        else {
            console.log("No datapoint returned");
        }
    callback(cw_value);
    }
    
)}

// End LISAsoft Cloudwatch code
