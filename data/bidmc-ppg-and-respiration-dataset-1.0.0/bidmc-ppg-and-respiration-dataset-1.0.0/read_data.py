import matplotlib.pyplot as plt
import wfdb

# 1. Giới hạn đọc 10 giây đầu tiên ngay từ lúc đọc file bằng sampto=125*10
record = wfdb.rdrecord('bidmc01', sampto=125*10)

# 2. In thông tin tổng quan ra Terminal
print('Tần số lấy mẫu (Fs):', record.fs)
print('Các kênh tín hiệu:', record.sig_name)
print('Kích thước dữ liệu (số mẫu x số kênh):', record.p_signal.shape)

# 3. In 5 mẫu dữ liệu đầu tiên
print('\n5 mẫu dữ liệu đầu tiên:')
print(record.p_signal[:5])

# 4. Vẽ biểu đồ (ĐÃ BỎ sampto ở dòng này)
wfdb.plot_wfdb(record=record, title='BIDMC Record 01')
plt.show()