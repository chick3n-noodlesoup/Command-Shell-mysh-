import signal
import parsing
import os
import sys
import json
import re

quit_status = False
pipe_separated = []
os.environ["PWD"] = "/home"

# This function is required in order to correctly switch the terminal foreground group to
# that of a child process.
def setup_signals() -> None:
    """
    Setup signals required by this program.
    """ 
    signal.signal(signal.SIGTTOU, signal.SIG_IGN)


def load_myshrc():
    if 'PROMPT' not in os.environ:
        os.environ['PROMPT'] = '>> '

    if 'MYSH_VERSION' not in os.environ:
        os.environ['MYSH_VERSION'] = '1.0'

    myshrc_path = os.path.join(os.getenv('MYSHDOTDIR', os.path.expanduser('~')), '.myshrc')

    try:
        with open(myshrc_path, 'r') as file:
            env_vars = json.load(file) 
    except json.JSONDecodeError:
        print("mysh: invalid JSON format for .myshrc", file=sys.stderr)
        return
    except FileNotFoundError:
        return
    
    for key, value in env_vars.items():
        valid = True
        if not isinstance(value, str):
            valid = False
            print(f"mysh: .myshrc: {key}: not a string", file=sys.stderr)
        else:
            for i in key:
                if not (i.isalnum() or i == "_"):
                    valid = False
                    print(f"mysh: .myshrc: {key}: invalid characters for variable name", file=sys.stderr)
                    break
        if valid:
            env_vars[key] = replace_env_vars(value, env_vars)
            os.environ[key] = env_vars[key]

def replace_env_vars(value, env_vars):

    while '${' in value:
        start = value.find('${')
        end = value.find('}', start)
        if end == -1:
            break
        var_name = value[start+2:end]
        var_value = os.getenv(var_name, " ")
        value = value[:start] + var_value + value[end+1:]
    return value


def pwd(cmd):
    if len(cmd) == 2:
        if cmd[1] == "-P":
            print(os.getcwd())
        elif cmd[1].startswith("-"):    
                print(f"pwd: invalid option: {cmd[1][0:2]}")
        else:
            print("pwd: not expecting any arguments")
    elif len(cmd) == 1:
        print(os.getenv("PWD"))
    else:
        if cmd[1].startswith("-"):    
                print(f"pwd: invalid option: {cmd[1][0:2]}")
        else:
            print("pwd: not expecting any arguments")


def cd(cmd):
    global cur_dir
    if len(cmd) > 2:
        print("cd: too many arguments")
    elif len(cmd) == 1:
        try:
            os.chdir("/home")
            os.environ["PWD"] = "/home"
        except:
            print("cd: permission denied: ~")
    else:
        cmd[1] = cmd[1].replace("~", "/home")
        if os.path.exists(cmd[1]):
            if os.path.isdir(cmd[1]):
                try:
                    os.chdir(cmd[1])
                    if os.path.islink(cmd[1]):
                        if os.path.isabs(cmd[1]):
                            os.environ["PWD"] = os.path.normpath(cmd[1])
                        else:
                            os.environ["PWD"] += "/" + os.path.normpath(cmd[1])
                    else:
                        os.environ["PWD"] = os.getcwd()
                except:
                    print(f"cd: permission denied: {cmd[1]}")
            else:
                print(f"cd: not a directory: {cmd[1]}")
        else:
            print(f"cd: no such file or directory: {cmd[1]}")


def exit(cmd):
    global quit_status
    if len(cmd) > 2:
        print("exit: too many arguments")
    elif len(cmd) == 1:
        quit_status = True
    else:
        if cmd[1].isdigit():
            quit_status = True
            sys.exit(int(cmd[1]))
        else:
            print(f"exit: non-integer exit code provided: {cmd[1]}")


def which(cmd):
    if len(cmd) == 1:
        print("usage: which command ...")
    else:
        for i in range(1,len(cmd)):
            path_not_found = True
            full_path = []
            if cmd[i] in ["pwd", "cd", "exit", "which", "var"]:
                print(f'{cmd[i]}: shell built-in command')
            else:
                dirs = os.environ.get('PATH',"").split(os.pathsep)
                for _dir in dirs:
                    potential_path = os.path.join(_dir, cmd[i])
                    if os.path.exists(potential_path) and os.access(potential_path, os.X_OK):
                        full_path.append(potential_path)
                        path_not_found = False
                if path_not_found:
                    print(f"{cmd[i]} not found")
                else:
                    print(full_path.pop(0))

def var(cmd):
    valid = True
    if len(cmd) == 3:
        for i in cmd[1]:
            if i.isalnum() or i == "_":
                continue
            else:
                valid = False
                print(f"var: invalid characters for variable {cmd[1]}")
                break
        if valid:
            index = 0
            valid_2 = True
            for i in cmd:
                var_value = substitute_variables(i)
                cmd[index] = var_value
                index += 1
            os.environ[cmd[1]] = cmd[2]
    elif len(cmd) == 4 and cmd[1].startswith("-"):
        if cmd[1] == "-s":
            cmd[2] = substitute_variables(cmd[2])

            if cmd[2] is not None:
                index = 0
                for i in cmd:
                    var_value = substitute_variables(i)
                    cmd[index] = var_value
                    index += 1
                os.environ[cmd[2]] = s_flag(cmd[3])
        else:
            print(f"var: invalid option: {cmd[1][0:2]}")
    else:
        print(f"var: expected 2 arguments, got {len(cmd)-1}")

def s_flag(command):
    cmd = parsing.split(command)
    read_fd, write_fd = os.pipe()

    index = 0
    for j in cmd:
        cmd[index] = j.replace("~", "/home")
        index += 1

    pid = os.fork()

    if pid == 0:  
        os.close(read_fd)
        os.dup2(write_fd, 1)
        os.close(write_fd)
        
        try:
            os.execvp(cmd[0], cmd)
        except PermissionError:
            print(f"mysh: permission denied: {cmd[0]}")
        except:
            print("oops")
    
    else:  
        os.close(write_fd)
        output = os.read(read_fd, 4096).decode()
        os.close(read_fd)
        os.wait()
        if output.count("\n") == 1:
            output = output.strip()
        return output


def execute_command(cmd):
    path_not_found = True

    dirs = os.environ.get('PATH', "").split(os.pathsep)
    for _dir in dirs:
        potential_path = os.path.join(_dir, os.path.normpath(cmd[0]))
        if os.path.exists(potential_path) and os.access(potential_path, os.X_OK):
            path_not_found = False
            break

    if path_not_found:
        try:
            os.execvp(cmd[0], cmd)
        except PermissionError:
            print(f"mysh: permission denied: {cmd[0]}")
        except:
            if "/" not in cmd[0]:
                print(f"mysh: command not found: {cmd[0]}")
            else:
                print(f"mysh: no such file or directory: {cmd[0]}")
    else:
        command_path = potential_path
        if os.path.isdir(command_path):
            print(f"mysh: is a directory: {command_path}")
        else:
            pid = os.fork()

            if pid == 0:
                os.setpgid(0, 0)
                child_process(cmd)

            elif pid > 1:
                try:
                    os.setpgid(pid, pid)
                except PermissionError:
                    pass

                tty_fd = os.open("/dev/tty", os.O_RDWR)
                os.tcsetpgrp(tty_fd, pid)
                os.waitpid(pid, 0)
                parent_pgid = os.getpgid(0)
                os.tcsetpgrp(tty_fd, parent_pgid)
                os.close(tty_fd)

        
def child_process(cmd):
    global quit_status
    index = 0
    valid_2 = True
    for i in cmd:
        var_value = substitute_variables(i)
        if var_value is not None:
            cmd[index] = var_value.replace("~", "/home")
            index += 1
        else:
            valid_2 = False
            break
    if valid_2:
        try:
            os.execvp(cmd[0], cmd)
        except PermissionError:
            print(f"mysh: permission denied: {cmd[0]}")
        except EOFError:
            quit_status = True
            print()
        finally:
            sys.exit(0)


def substitute_variables(command):
    valid = True
    placeholders = []

    def replace_match(match):
        nonlocal valid
        var_name = match.group(1)
        for i in var_name:
            if not (i.isalnum() or i == "_"):
                valid = False
                print(f"mysh: syntax error: invalid characters for variable {var_name}", file=sys.stderr)
                return ""

        return os.getenv(var_name, '')

    def store_placeholder(match):
        placeholders.append(match.group(0))
        return "__ESCAPED__"

    def restore_placeholder(match):
        return placeholders.pop(0)[1:]  

    command = re.sub(r'\\\$\{([^}]+)\}', store_placeholder, command)
    command = re.sub(r'(?<!\\)\$\{([^}]+)\}', replace_match, command)
    command = re.sub(r'__ESCAPED__', restore_placeholder, command)

    if valid:
        return command
    else:
        return None


def main() -> None:
    global quit_status
    setup_signals()
    while not quit_status:
        try:
            user_input = input(os.getenv('PROMPT'))
            split_input = parsing.split(user_input.replace("\\","\\\\"))
            #print(split_input)
            cmd = split_input[0]
            if cmd == "pwd":
                pwd(split_input)
            elif cmd == "cd":
                cd(split_input)
            elif cmd == "exit":
                exit(split_input)
            elif cmd == "which":
                which(split_input)
            elif cmd == "var":
                var(split_input)
            else:
                execute_command(split_input)
                
        except IndexError:
            pass
        except EOFError:
            quit_status = True
            print()
        except KeyboardInterrupt:
            quit_status = False
            print()
        except ValueError as error_msg:
            if str(error_msg) == "No closing quotation":
                print("mysh: syntax error: unterminated quote")


if __name__ == "__main__":
    load_myshrc()
    main()
