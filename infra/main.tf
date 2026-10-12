# ---------- Lookups ----------

data "aws_availability_zones" "available" {
  state = "available"
}

# Latest Ubuntu 24.04 LTS for ARM (Graviton). Owner is Canonical's account.
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"]
  }
}

data "aws_route53_zone" "main" {
  name = var.domain_zone
}

# ---------- Network: one public subnet, no NAT gateway ----------

resource "aws_vpc" "main" {
  cidr_block           = "10.20.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "docsearch" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "docsearch" }
}

resource "aws_subnet" "public" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.20.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]

  tags = { Name = "docsearch-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "docsearch-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# ---------- Firewall: HTTP/HTTPS in, nothing else. No SSH. ----------

resource "aws_security_group" "web" {
  name        = "docsearch-web"
  description = "HTTP and HTTPS from anywhere. Shell access is via SSM, not SSH."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "docsearch-web" }
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  security_group_id = aws_security_group.web.id
  description       = "HTTP (Caddy redirects to HTTPS; also used for certificate issuance)"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.web.id
  description       = "HTTPS"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.web.id
  description       = "Outbound: package installs, GitHub, OpenAI, AWS APIs"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# ---------- Instance role: SSM Session Manager + reading /docsearch/* parameters ----------
# AmazonSSMManagedInstanceCore covers both registering with Session Manager
# and ssm:GetParameter. SecureStrings use the AWS managed aws/ssm key, whose
# key policy already allows decryption through SSM within this account.

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name               = "docsearch-instance"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "instance" {
  name = "docsearch-instance"
  role = aws_iam_role.instance.name
}

# ---------- Server ----------

resource "aws_instance" "app" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.web.id]
  iam_instance_profile   = aws_iam_instance_profile.instance.name

  user_data                   = templatefile("${path.module}/user_data.sh", { repo_url = var.repo_url })
  user_data_replace_on_change = true

  # Standard CPU credits: if the instance runs hot, it slows down instead of billing for extra credits.
  credit_specification {
    cpu_credits = "standard"
  }

  # Require IMDSv2 (blocks a class of SSRF credential-theft attacks).
  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 20
    encrypted   = true
  }

  # Don't replace the server every time Canonical publishes a new AMI.
  lifecycle {
    ignore_changes = [ami]
  }

  tags = { Name = "docsearch" }
}

resource "aws_eip" "app" {
  domain   = "vpc"
  instance = aws_instance.app.id

  tags       = { Name = "docsearch" }
  depends_on = [aws_internet_gateway.main]
}

resource "aws_route53_record" "app" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "${var.subdomain}.${var.domain_zone}"
  type    = "A"
  ttl     = 300
  records = [aws_eip.app.public_ip]
}
