// IPv4-only allow-list (no IPv6 support — viewers on IPv6 are rejected).
// CIDR list is embedded at Terraform plan time; this function does not
// fetch or evaluate anything at runtime beyond the viewer IP.
var ALLOWED_CIDRS = ${allowed_cidrs_json};

function ipToInt(ip) {
  var parts = ip.split('.');
  if (parts.length !== 4) return null;
  var n = 0;
  for (var i = 0; i < 4; i++) {
    var octet = parseInt(parts[i], 10);
    if (isNaN(octet) || octet < 0 || octet > 255) return null;
    n = (n << 8) | octet;
  }
  return n >>> 0;
}

function ipAllowed(ip) {
  var ipInt = ipToInt(ip);
  if (ipInt === null) return false;
  for (var i = 0; i < ALLOWED_CIDRS.length; i++) {
    var cidrParts = ALLOWED_CIDRS[i].split('/');
    var netInt = ipToInt(cidrParts[0]);
    var bits = parseInt(cidrParts[1], 10);
    if (netInt === null || isNaN(bits)) continue;
    var mask = bits === 0 ? 0 : (0xFFFFFFFF << (32 - bits)) >>> 0;
    if ((ipInt & mask) === (netInt & mask)) return true;
  }
  return false;
}

function handler(event) {
  var request = event.request;
  if (!ipAllowed(event.viewer.ip)) {
    return {
      statusCode: 403,
      statusDescription: 'Forbidden',
      body: { encoding: 'text', data: 'Forbidden' }
    };
  }
  return request;
}
