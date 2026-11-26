# Time sync used for one-way latency (publish time on the Pi vs receive time on the laptop)

Laptop (`/etc/chrony/chrony.conf`): serve time on the lab network.

    allow 192.168.1.0/24
    local stratum 10

Pi (`/etc/chrony/chrony.conf`): follow the laptop closely.

    server <laptop-ip> iburst prefer minpoll 0 maxpoll 2

Check before every run: the laptop is the selected source, LastRx is small, |offset| <= 1 ms, and new
samples keep being accepted (`run_field.py` does this check and refuses otherwise).
