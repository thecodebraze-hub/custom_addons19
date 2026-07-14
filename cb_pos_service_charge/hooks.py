def post_init_hook(env):
    env["pos.config"]._assign_default_service_charge_configs()
