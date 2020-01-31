def data_to_block(data):
    block_data = bytearray()
    cur_i = 0
    while cur_i < len(data):
        block_length = min(len(data) - cur_i, 2 ** 16 - 1)
        data_block = data[cur_i: cur_i + block_length]
        cur_i += block_length
        if cur_i == len(data):
            block_data.append(64)
        else:
            block_data.append(0)
        block_data.append(block_length // 256)
        block_data.append(block_length % 256)
        block_data += data_block
    return block_data


def data_from_block(data):
    result_data = bytearray()
    cur_i = 0
    while cur_i < len(data):
        cur_i += 1
        length = data[cur_i] * 256 + data[cur_i + 1]
        cur_i += 2
        result_data += data[cur_i: cur_i + length]
        cur_i += length
    return result_data


def data_to_compress(data):
    compressed_data = bytearray()
    cur_i = 0
    while cur_i < len(data):
        block_length = min(len(data) - cur_i, 2 ** 7 - 1)
        data_block = data[cur_i: cur_i + block_length]
        cur_i += block_length
        compressed_data.append(block_length)
        compressed_data += data_block
    return compressed_data


def data_from_compress(data):
    result = bytearray()
    cur_i = 0
    while cur_i < len(data):
        flag = data[cur_i]
        if not (flag & (2**7)):
            cur_i += 1
            result += data[cur_i:cur_i + flag]
            cur_i += flag
        elif not (flag & (2**6)):
            # Replicated byte
            cur_i += 1
            flag = flag ^ (2**7)
            result += data[cur_i] * flag
        else:
            # Filler string
            # Used for restart marker, so safe to ignore
            sz = cur_i ^ (2**7) ^ (2**6)
            cur_i += 1 + sz
    return result
