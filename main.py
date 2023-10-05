import argparse
import datetime

from builder import MultimodalTodDatasetBuilder

if __name__=="__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build_prompt", action="store_true", default=False
    )
    parser.add_argument(
        "--config_file", type=str, default='configs/api.json'
    )
    parser.add_argument(
        "--data_dir", type=str, default='/data/ai_hub'
    )
    parser.add_argument(
        "--prompt_dir", type=str, default="prompt", help="Path for fewshot examples"
    )
    parser.add_argument(
        "--log_path", type=str, default='log/'
    )
    today = datetime.datetime.now()
    parser.add_argument(
        "--logger_name", type=str, default=f"{today.strftime('%m%d')}_build_dataset"
    )
    parser.add_argument(
        "--seed", type=int, default=19
    )
    args, leftovers = parser.parse_known_args()

    data_builder = MultimodalTodDatasetBuilder(args=args, leftovers=leftovers)


    if args.build_prompt:
        data_builder.build_gpt_prompt()
        
    data_builder.build()
                

            
            
            