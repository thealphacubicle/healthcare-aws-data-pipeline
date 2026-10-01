# 6. Serving: Streamlit on a single EC2 instance in the default VPC, served on
# port 80 at the instance's default public DNS name
# (http://ec2-<ip>.compute-1.amazonaws.com). No domain, load balancer, or
# Elastic IP: the auto-assigned public IP/DNS changes if the instance is
# stopped and started (e.g. by the budget action); `terraform output
# dashboard_url` (after `terraform refresh`) shows the current one.

data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

data "aws_vpc" "default" {
  default = true
}

resource "aws_s3_object" "dashboard_app" {
  bucket      = aws_s3_bucket.this["artifacts"].id
  key         = "dashboard/app.zip"
  source      = "${local.build_dir}/app.zip"
  source_hash = filemd5("${local.build_dir}/app.zip")
}

resource "aws_security_group" "dashboard" {
  name        = "${local.name}-dashboard"
  description = "Streamlit dashboard"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "Streamlit over HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.dashboard_allowed_cidrs
  }

  egress {
    description = "Outbound HTTPS to AWS APIs, SSM, and PyPI"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "dashboard" {
  name               = "${local.name}-dashboard"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "dashboard_ssm" {
  role       = aws_iam_role.dashboard.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "dashboard" {
  statement {
    sid = "RunAthenaQueries"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:StopQueryExecution",
      "athena:GetWorkGroup",
    ]
    resources = [aws_athena_workgroup.this.arn]
  }

  statement {
    sid     = "ReadCatalog"
    actions = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:GetPartitions"]
    resources = [
      "arn:${local.partition}:glue:${var.aws_region}:${local.account_id}:catalog",
      aws_glue_catalog_database.this.arn,
      "arn:${local.partition}:glue:${var.aws_region}:${local.account_id}:table/${aws_glue_catalog_database.this.name}/*",
    ]
  }

  statement {
    sid       = "ReadCuratedTables"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.this["curated"].arn}/${local.curated_tables_prefix}/*"]
  }

  statement {
    sid       = "ListCuratedTables"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.this["curated"].arn]
  }

  statement {
    sid = "AthenaResults"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.this["athena_result"].arn}/*"]
  }

  statement {
    sid       = "AthenaResultsBucket"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.this["athena_result"].arn]
  }

  statement {
    sid       = "DownloadApp"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.this["artifacts"].arn}/${aws_s3_object.dashboard_app.key}"]
  }
}

resource "aws_iam_role_policy" "dashboard" {
  role   = aws_iam_role.dashboard.id
  policy = data.aws_iam_policy_document.dashboard.json
}

resource "aws_iam_instance_profile" "dashboard" {
  name = "${local.name}-dashboard"
  role = aws_iam_role.dashboard.name
}

resource "aws_instance" "dashboard" {
  ami                         = data.aws_ssm_parameter.al2023_ami.value
  instance_type               = var.dashboard_instance_type
  iam_instance_profile        = aws_iam_instance_profile.dashboard.name
  vpc_security_group_ids      = [aws_security_group.dashboard.id]
  associate_public_ip_address = true

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = templatefile("${path.module}/templates/dashboard_user_data.sh.tftpl", {
    app_s3_uri = "s3://${aws_s3_bucket.this["artifacts"].id}/${aws_s3_object.dashboard_app.key}"
    region     = var.aws_region
    database   = aws_glue_catalog_database.this.name
    table      = var.curated_table_name
    workgroup  = aws_athena_workgroup.this.name
  })

  tags = {
    Name = "${local.name}-dashboard"
  }

  lifecycle {
    # A newer AMI should not replace the running instance on every apply.
    ignore_changes = [ami]
  }
}
