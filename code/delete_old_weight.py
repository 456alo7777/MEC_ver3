#to delete old weight files
import os 
import glob

path = '/workspaces/MEC_ver3/code'

files = glob.glob(os.path.join(path, "*.h5f.*"))


for f in files:
    os.remove(f)