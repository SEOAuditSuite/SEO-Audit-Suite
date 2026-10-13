# Synthetic TLS test fixture

`test-only-tls.crt` and `test-only-tls.key` are a disposable, self-signed certificate
and public test-only private key for `audit.example.test`. They are NOT production
credentials. Never deploy or add this certificate to an operating-system trust
store. The regression test explicitly trusts it in one scoped Python SSL context
and verifies both hostname mismatch and default untrusted-certificate rejection.
No OpenSSL installation is needed to run the tests. Replace the synthetic pair
before its certificate expires in 2036; do not weaken verification.
