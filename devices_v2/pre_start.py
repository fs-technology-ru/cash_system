from redis import Redis

from configs import REDIS_HOST, REDIS_PORT

redis = Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

redis.set('bill_dispenser:upper_lvl', 10000)
redis.set('bill_dispenser:lower_lvl', 5000)
redis.set('bill_dispenser:upper_count', 500)
redis.set('bill_dispenser:lower_count', 500)

redis.set('max_bill_count', 1400)
redis.set('bill_count', 800)

redis.delete("available_devices_cash")
redis.sadd("available_devices_cash", 'bill_acceptor', 'bill_dispenser')
redis.sadd("available_devices_cash", 'coin_acceptor')
redis.sadd("available_devices_cash", 'bill_acceptor', 'bill_dispenser', 'coin_acceptor')
