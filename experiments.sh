python sbatch.py gres="gpu:1" partition=long time=24:00:00 cpus=4 mem=32GB py_args="--mode train --config-yml configs/is2re/10k/sfarinet/sfarinet.yml --note='test 1st sfarinet'" env=ocp

python sbatch.py gres="gpu:1" partition=long time=24:00:00 cpus=4 mem=32GB py_args="--mode train --config-yml configs/is2re/10k/sfarinet/sfarinet.yml --optim.batch_size=64 --optim.eval_batch_size=64 --optim.lr_initial=0.005 --optim.lr_milestones=[1500, 2000, 3000] --optim.warmup_steps=400 --optim.warmup_factor=0.2 --optim.max_epochs=20 --note='test 1st sfarinet'" env=ocp

python sbatch.py gres="gpu:1" partition=long time=24:00:00 cpus=4 mem=32GB py_args="--mode train --config-yml configs/is2re/10k/sfarinet/sfarinet.yml --optim.batch_size=64 --optim.eval_batch_size=64 --optim.lr_initial=0.005 --optim.lr_milestones=[1500, 2000, 3000] --optim.warmup_steps=400 --optim.warmup_factor=0.2 --optim.max_epochs=20 --model.hidden_channels=256 --model.num_interactions=3 --model.num_gaussians=100 --model.cutoff=6.0 --model.num_filters=128 --note='test 1st sfarinet'" env=ocp