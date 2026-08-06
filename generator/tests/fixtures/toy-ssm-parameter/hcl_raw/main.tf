# Reference fixture for generator/check_reference_paths.py -- NOT a
# generated file, hand-authored to be oracle-CORRECT per
# specs/_toy/toy-ssm-parameter.yaml's oracle.intent. Dropped in place of the
# generated task's own main.tf (entry_file); provider.tf and everything else
# comes from the real generated tasks/anchor/toy-ssm-parameter-hcl-raw/
# environment/. References the parameter's own `.name` (an agent-supplied
# literal echo, plan-time-known) rather than its provider-computed `.arn` --
# see the G2 fix note in specs/_toy/toy-ssm-parameter.yaml's
# policy-actions-read-only assert for why that choice matters: it's what
# keeps `values.policy` resolvable at plan time for this fixture.
resource "aws_ssm_parameter" "greeting" {
  name  = "/cdktn-bench-toy/greeting"
  type  = "String"
  value = "hello-from-cdktn-bench"
}

resource "aws_iam_role" "reader" {
  name = "cdktn-bench-toy-ssm-reader"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "reader_policy" {
  name = "read-greeting-parameter"
  role = aws_iam_role.reader.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameter", "ssm:GetParameters"]
      Resource = "arn:*:ssm:*:*:parameter${aws_ssm_parameter.greeting.name}"
    }]
  })
}
