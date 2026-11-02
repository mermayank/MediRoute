"""Small, deterministic policy functions used by the pharmacy workflow.
Rules are config-driven so they can change when online pharmacy rules are finalised."""
PROHIBITED_ONLINE = {'X', 'NARCOTIC'}
PRESCRIPTION_REQUIRED = {'H', 'H1'}
KNOWN_SCHEDULES = {'OTC', 'H', 'H1', 'X', 'NARCOTIC'}
DISPATCHABLE_STATES = {'verified', 'ready_to_pack', 'packed'}

def _schedule(value) -> str:
    return (value or '').strip().upper()

def validate_online_item(schedule: str, has_prescription: bool) -> tuple[bool, str]:
    s = _schedule(schedule)
    if s not in KNOWN_SCHEDULES:
        return False, 'This item has no valid schedule classification and cannot be sold online.'
    if s in PROHIBITED_ONLINE:
        return False, 'This item cannot be sold through this online ordering flow.'
    if s in PRESCRIPTION_REQUIRED and not has_prescription:
        return False, 'A valid prescription upload is required.'
    return True, ''

def can_dispatch(items: list[dict], order_status: str) -> tuple[bool, str]:
    if order_status not in DISPATCHABLE_STATES:
        return False, 'Order is not in a dispatchable state.'
    if not items:
        return False, 'An order with no items cannot be dispatched.'
    for item in items:
        s = _schedule(item.get('schedule'))
        if s not in KNOWN_SCHEDULES:
            return False, 'Every item needs a valid schedule classification.'
        if s in PROHIBITED_ONLINE:
            return False, 'Prohibited items cannot be dispatched.'
        if item.get('approval_status') != 'approved':
            if s in PRESCRIPTION_REQUIRED:
                return False, 'Every Schedule H/H1 item must be approved before dispatch.'
            return False, 'Every order item must be approved before dispatch.'
    return True, ''