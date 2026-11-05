# Keep the plugin directory clean: no __pycache__ next to the code under test.
import sys

sys.dont_write_bytecode = True
