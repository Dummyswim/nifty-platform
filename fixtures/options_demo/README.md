SYNTHETIC option data for tests and `make e2e` only. Hand-generated, not recorded from any exchange
or broker; prices come from a Black-Scholes toy (sigma 15 %, r 6.5 %). `build.py` writes it into a
database given as a connection; it must never be loaded into the dev database.
