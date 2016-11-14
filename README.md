# Elk
This repository contains the Automation to create a monitoring environment in an AWS Space.

The script '[elk.py](/elk.py)' is the main entry point for any of the functionality within this repository.

## Usage and examples

```
usage: python3 elk.py [-h] [-p PROFILE] [-n NAME] [-a ACTION]

optional arguments:
  -h, --help            show this help message and exit
  -p PROFILE, --profile PROFILE
                        Which profile to use (from your aws credentials file.
                        default: default
  -n NAME, --name NAME  What name to give the elk instance. default: elk
  -a ACTION, --action ACTION
                        The action to perform. options: create, or delete.
                        Delete will delete all elk objects with the provided
                        name (-n). default: create
```

When running the elk.py script, it will only pull metrics for the folders that exist under the '[lambdas](/lambdas)' folder.
By default, this includes ec2, rds, and ebs metrics from cloudwatch, as well as a curator to delete anything older than a month and avoid the es domain becoming full.
If you would like your elk domain to include other metrics, there are options in the '[additional-lambdas](/additional-lambdas)' folder. 
To use these, BEFORE running the elk.py script, copy the folder for the metrics you are interested in from additional-lambdas to lambdas.
eg. '/additional-lambdas/METRICS_OF_INTEREST' -----COPY----> '/lambdas/METRICS_OF_INTEREST'

## Lambda specifics

### cost_metrics.js

Setup process for cost_metrics.js:
* Copy the cost_metrics folder from additional-lambdas to the lambdas folder.
* Run elk.py and wait for the elasticsearch domain to finish creating.
* Copy the ARN from the IAM Role that has been created for you (YOURELKNAME_processing_lambda_role)
* Log into your billing account.
* Find, or create an IAM Policy + Role that allows access to your billing S3 bucket and save the ARN somewhere. (example below)

```
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "s3:ListAllMyBuckets",
            "Resource": "arn:aws:s3:::*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:ListBucket",
                "s3:GetBucketLocation"
            ],
            "Resource": "arn:aws:s3:::mybillingbucket"
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject"
            ],
            "Resource": "arn:aws:s3:::mybillingbucket/*"
        }
    ]
}
```

* Edit the Trust Relationship and add a statement that allows the lambda ARN from step 3 to assume the IAM role from step 5. (Example Below)

```
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::123456789:role/YOURELKNAME_processing_lambda_role"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

* log back into the elk AWS account.
* Find the Cloudwatch Rule (YOURELKNAME_cost_metrics) which was created for you.
* Update the bucket, and role_arn in the json data that it sends to point to the billing bucket, and the IAM role arn from your billing account