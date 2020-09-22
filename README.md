# Twilio Webhook Muxer

Webhook Muxer is a Lambda function that receives Twilio webhooks and
re-transmits them to downstream locations. It's useful because Twilio only
supports adding a single webhook URL to a phone number for incoming calls and
texts, but you might want to deliver those webhooks to multiple locations.

## Twilio Signatures

Twilio webhook signatures include the destination URL, so you can't just
forward a webhook payload sent to `https://my-webhook-muxer.com` onto
a downstream location at `https://my-downstream-webhook-receiver.com`, because
the downstream location will get a signature for `https://my-webhook-muxer.com`.
To make sure that downstream locations can treat the webhooks coming from
Webhook Muxer as if they're coming from Twilio, we need to rewrite the
signature.

When a Twilio webhook comes in, we verify the signature, and then rewrite that
signature for each downstream location so that it matches the downstream
location's URL.

## Deploy Twilio Webhook Muxer

1. Fork this repo
2. Edit serverless.yml to reflect your downstream locations and Twilio credentials
3. If you've configured a custom domain name in `serverless.yml`, run
   `yarn sls create_domain -s prod` to create that domain name.
   - Also run `yarn sls create_domain -s staging` and `yarn sls create_domain -s local` if
     you plan to use the staging/local stages.
4. Deploy it with `yarn sls deploy -s prod` (or `-s staging`, or `-s local`,
   if you want to have multiple deployment stages)
5. When you deploy, it will print out the URL that you should point your
   Twilio webhook at.

Then, just point your Twilio webhooks at the muxer URL using HTTP POST. The
muxer will validate the signature and forward the request on to all the downstream
locations with an updated signature (also using an HTTP POST -- GET webhooks are
not supported.)
