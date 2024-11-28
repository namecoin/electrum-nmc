# Shared Namecoin Core / Electrum-NMC Qt GUI

Upstream Bitcoin Core and Electrum both use Qt for their GUI. Therefore, to minimize duplicated Namecoin-specific GUI code, Namecoin Core and Electrum-NMC share their Qt GUI form files. This requires an extra build step in Electrum-NMC (handled by the `contrib/make_qt_forms` script), since upstream Electrum does not use form files.

There are some differences between the Namecoin Core and Electrum-NMC versions of the form files. They are mostly due to:

1. Some features are implemented in Namecoin Core but not Electrum-NMC, or vice versa.
2. Electrum-NMC includes shim implementations of the Bitcoin Core widgets `QPayToEdit` and `QValidatedLineEdit`.

Pull requests to decrease the diff size would probably be welcome.

If you're copying changes in the form files between Namecoin Core and Electrum-NMC, and you get confusing errors that mention any of the Bitcoin Core widgets mentioned above, it is likely that you accidentally changed the references to the shims.
