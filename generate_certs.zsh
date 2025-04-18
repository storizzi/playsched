#!/bin/zsh

# --- Configuration ---
# Hostname for the server certificate. Use localhost for local development.
SERVER_NAME="localhost"
# Validity days
CA_DAYS=3650  # Long validity for root CA
CERT_DAYS=825 # Validity for server cert

# Output file names
CA_KEY="myCA.key"
CA_CERT="myCA.pem"
SERVER_KEY="${SERVER_NAME}.key"
SERVER_CSR="${SERVER_NAME}.csr"
SERVER_CERT="${SERVER_NAME}.crt"
SERVER_EXT="${SERVER_NAME}.ext"
SERIAL_FILE="myCA.srl"

# Certificate Subject Details (Modify if desired, but CN for server MUST match SERVER_NAME or SAN)
COUNTRY="FR"
STATE="Nouvelle-Aquitaine"
LOCALITY="Nontron"
ORGANIZATION="Local Development CA"
ORG_UNIT="Dev CA"
CA_COMMON_NAME="My Local Development CA" # Name for your Certificate Authority
SERVER_COMMON_NAME=$SERVER_NAME # Common Name for server cert (matches hostname)
EMAIL="admin@${SERVER_NAME}.local" # Placeholder email

echo "--- Generating Certificate Authority (CA) ---"
echo "Output files: $CA_KEY, $CA_CERT"

# 1. Generate CA Private Key (unencrypted using -nodes)
openssl genrsa -out $CA_KEY 2048
if [ $? -ne 0 ]; then echo "Error generating CA key. Exiting."; exit 1; fi

# 2. Generate Root CA Certificate (Self-signed) using the CA key
#    (-subj avoids interactive prompts)
openssl req -x509 -new -nodes -key $CA_KEY -sha256 -days $CA_DAYS \
    -subj "/C=$COUNTRY/ST=$STATE/L=$LOCALITY/O=$ORGANIZATION/OU=$ORG_UNIT/CN=$CA_COMMON_NAME/emailAddress=$EMAIL" \
    -out $CA_CERT
if [ $? -ne 0 ]; then echo "Error generating CA certificate. Exiting."; exit 1; fi

echo "\n--- Generating Server Certificate for '$SERVER_NAME' ---"
echo "Output files: $SERVER_KEY, $SERVER_CSR, $SERVER_EXT, $SERVER_CERT"

# 3. Generate Server Private Key
openssl genrsa -out $SERVER_KEY 2048
if [ $? -ne 0 ]; then echo "Error generating server key. Exiting."; exit 1; fi

# 4. Create Server Certificate Signing Request (CSR)
openssl req -new -key $SERVER_KEY \
    -subj "/C=$COUNTRY/ST=$STATE/L=$LOCALITY/O=$ORGANIZATION/OU=$ORG_UNIT/CN=$SERVER_COMMON_NAME/emailAddress=$EMAIL" \
    -out $SERVER_CSR
if [ $? -ne 0 ]; then echo "Error generating server CSR. Exiting."; exit 1; fi

# 5. Create Certificate Extensions Configuration File (SANs are important!)
cat > $SERVER_EXT <<-EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
subjectAltName = @alt_names
# Optional: Add clientAuth if needed, serverAuth is typical for web servers
# extendedKeyUsage=serverAuth,clientAuth
[alt_names]
DNS.1 = $SERVER_NAME
IP.1 = 127.0.0.1
# Add more DNS names (DNS.2 = myotherlocal.dev) or IPs (IP.2 = ::1 for IPv6) if needed
EOF

# 6. Create the CA-signed Server Certificate using the CSR and Extensions
#    (-CAcreateserial handles the myCA.srl file automatically)
openssl x509 -req -in $SERVER_CSR \
    -CA $CA_CERT -CAkey $CA_KEY \
    -CAcreateserial \
    -out $SERVER_CERT -days $CERT_DAYS -sha256 \
    -extfile $SERVER_EXT
if [ $? -ne 0 ]; then echo "Error signing server certificate. Exiting."; exit 1; fi

echo "\n--- Certificate Generation Complete ---"
echo " CA Certificate:  $CA_CERT  (Import this into OS/Browser Authorities)"
echo " CA Private Key:  $CA_KEY  (Keep safe, needed to sign more certs)"
echo " Server Cert:     $SERVER_CERT  (Use in Flask)"
echo " Server Key:      $SERVER_KEY  (Use in Flask)"

# Optional cleanup of intermediate files
# echo "\nCleaning up intermediate files (.csr, .ext)..."
# rm $SERVER_CSR $SERVER_EXT

echo "\n--- NEXT STEPS ---"
echo "1. Import '$CA_CERT' into your Operating System's and/or Browser's Trust Store as an 'Authority'."
echo "2. Configure Flask to use '$SERVER_CERT' and '$SERVER_KEY'."

exit 0