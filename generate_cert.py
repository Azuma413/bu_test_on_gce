from OpenSSL import crypto
import os

def generate_self_signed_cert():
    # Generate key
    key = crypto.PKey()
    key.generate_key(crypto.TYPE_RSA, 2048)

    # Generate certificate
    cert = crypto.X509()
    cert.get_subject().CN = "34.133.108.164"
    
    # Add Subject Alternative Name
    san_list = ["IP:34.133.108.164"]
    san = crypto.X509Extension(
        b"subjectAltName",
        False,
        ", ".join(san_list).encode()
    )
    cert.add_extensions([san])
    cert.get_subject().C = "JP"
    cert.get_subject().ST = "Tokyo"
    cert.get_subject().L = "Tokyo"
    cert.get_subject().O = "Development"
    cert.get_subject().OU = "Development"
    
    cert.set_serial_number(1000)
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(365*24*60*60)  # Valid for one year
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(key)
    cert.sign(key, 'sha256')

    # Write certificate
    with open("server.crt", "wb") as f:
        f.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))

    # Write private key
    with open("server.key", "wb") as f:
        f.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, key))

if __name__ == '__main__':
    generate_self_signed_cert()
