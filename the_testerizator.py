from modules.mobsat.mobsat import MobSat
import asyncio 
a = MobSat()
a._do_init()

a._execute_step()

asyncio.run(a._execute_step())
