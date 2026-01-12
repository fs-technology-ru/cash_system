async def payment_system_cash_commands(command_data, api):
    """Выполнение команды на основе полученной из pubsub"""
    command = command_data.get('command')
    command_id = command_data.get('command_id')
    data = command_data.get('data')
    response = {
        "command_id": command_id,
        "success": False,
        "message": None,
        "data": None
    }
    if command == 'init_devices':
        response_data = await api.init_devices()

    elif command == 'start_accepting_payment':
        target_amount = data.get("amount", 0)
        response_data = await api.start_accepting_payment(target_amount)

    elif command == 'stop_accepting_payment':
        response_data = await api.stop_accepting_payment()

    elif command == 'test_dispense_change':
        is_bill = data.get('is_bill')
        is_coin = data.get('is_coin')
        response_data = await api.test_dispense_change(is_bill, is_coin)

    elif command == 'dispense_change':
        amount = data.get('amount')
        response_data = await api.dispense_change(amount)

    elif command == 'bill_acceptor_set_max_bill_count':
        value = data.get('value')
        response_data = await api.bill_acceptor_set_max_bill_count(value)

    elif command == 'bill_acceptor_reset_bill_count':
        response_data = await api.bill_acceptor_reset_bill_count()

    elif command == 'bill_acceptor_status':
        response_data = await api.bill_acceptor_status()

    elif command == 'set_bill_dispenser_lvl':
        upper_lvl = data.get('upper_lvl')
        lower_lvl = data.get('lower_lvl')
        response_data = await api.set_bill_dispenser_lvl(upper_lvl, lower_lvl)

    elif command == 'set_bill_dispenser_count':
        upper_count = data.get('upper_count')
        lower_count = data.get('lower_count')
        response_data = await api.set_bill_dispenser_count(upper_count, lower_count)

    elif command == 'bill_dispenser_status':
        response_data = await api.bill_dispenser_status()

    elif command == 'bill_dispenser_reset_bill_count':
        response_data = await api.bill_dispenser_reset_bill_count()

    elif command == 'coin_system_add_coin_count':
        value = data.get('value')
        denomination = data.get('denomination')
        response_data = await api.coin_system_add_coin_count(value, denomination)

    elif command == 'coin_system_status':
        response_data = await api.coin_system_status()

    elif command == 'coin_system_cash_collection':
        response_data = await api.coin_system_cash_collection()

    else:
        response_data = {}

    response.update(response_data)
    return response
