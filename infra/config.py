import pulumi

# Read the configuration for this stack.
stack_config = pulumi.Config()
stack = pulumi.get_stack()
target_domain = stack_config.require('targetDomain')
path_to_website_contents = stack_config.require('pathToWebsiteContents')
certificate_arn = stack_config.get('certificateArn')
tags = {"Environment": stack, "Name": target_domain}
