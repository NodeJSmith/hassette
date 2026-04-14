from typing import Union

# value_type = (int, float, str) becomes Union[int, float, str]
# TypeRegistry tries: str → int, then str → float, then keeps as str
