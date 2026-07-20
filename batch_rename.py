import os
import argparse

def batch_rename(directory, prefix='', search='', replace='', dry_run=True):
    """
    파일 이름을 일괄적으로 변경하는 함수
    """
    if not os.path.isdir(directory):
        print(f"Error: '{directory}'는 유효한 디렉토리가 아닙니다.")
        return

    files = os.listdir(directory)
    print(f"총 {len(files)}개의 항목을 발견했습니다.")
    
    count = 0
    for filename in files:
        # 현재 파일의 전체 경로
        old_path = os.path.join(directory, filename)
        
        # 디렉토리는 제외하고 파일만 처리
        if not os.path.isfile(old_path):
            continue

        # 새로운 파일 이름 결정
        new_filename = filename
        
        # 1. 접두사 추가
        if prefix:
            new_filename = prefix + new_filename
            
        # 2. 특정 문자열 치환
        if search:
            new_filename = new_filename.replace(search, replace)

        if filename == new_filename:
            continue

        new_path = os.path.join(directory, new_filename)

        if dry_run:
            print(f"[Dry-run] {filename} -> {new_filename}")
        else:
            try:
                os.rename(old_path, new_path)
                print(f"[Success] {filename} -> {new_filename}")
                count += 1
            except Exception as e:
                print(f"[Error] {filename} 변경 실패: {e}")

    if dry_run:
        print("\n이것은 시뮬레이션입니다. 실제로 변경하려면 --execute 옵션을 사용하세요.")
    else:
        print(f"\n총 {count}개의 파일 이름을 변경했습니다.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="파일 이름 일괄 변경 도구")
    parser.add_argument("dir", help="대상 디렉토리 경로")
    parser.add_argument("--prefix", default="", help="파일명 앞에 붙일 접두사")
    parser.add_argument("--search", default="", help="찾을 문자열")
    parser.add_argument("--replace", default="", help="바꿀 문자열")
    parser.add_argument("--execute", action="store_true", help="실제로 파일 이름을 변경합니다 (지정하지 않으면 시뮬레이션)")

    args = parser.parse_args()

    batch_rename(
        args.dir, 
        prefix=args.prefix, 
        search=args.search, 
        replace=args.replace, 
        dry_run=not args.execute
    )
