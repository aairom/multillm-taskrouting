## Project Development Rule

When working with projects:

1. **Project Context Guide**: Always check the links provided here to access the source code repositories for implementation:
   
2. **Project Structure**: Follow these conventions:
   - The documents of the project should be created in "Docs" folder except readme.md
   - Always provide a Mermaid flow architecture for the project in the "Architecture.md" file
   - All the BASH scripts if needed, should be written in "scripts" folder
   - All the input documents are to be found in "input" folder
   - All the documents in "input" folder should be processed recurssively.
   - All the output documents which are asked to be provided should be writen in timestamped format in "output" folder
   - The result documents should be written in "output" folder, if the "output" folder does not exist, it should be created
   - Always provide README.md with architecture + workflow diagrams as described
   - Always provide a Quickstart.md document in "Docs" folder
   - Always add the "Licence" type for the code in "Readme.md"
   - Always provide a ".gitignore" file which filters/ignores any ".env" files or any folders whichs' names start with "_" (underscore) to be pushed to GitHub (e.g.: _sources/, _images/, _docs/... ).
   - In the ".gitignore" add an entry to avoid sending ".playwright-mcp" folder to remote repository
3. **Key Patterns**:
   - Always test the functionnality of the code you provide 
   - When you make updates/enhancements and/or correct the bugs, update the existing documents and scripts, don't create new ones
   - Always provide a virtual environment for Python applications.
   - Always provide a script to lauch the application in detached mode which displays the URL to access the application on the console
   - Always provide a script to shutdown the application gracefully
   - If you find files in the folders which were not made by you, don't delete them
   - When building applications, never hard code the information inside the application (e.g: apiKey, email address, URL...) but provide an ".env.example" file with the variables to be saved as ".env" file to run the application 
4. **Misc**:
   - On a MacOS platform, don't use the port 5000, it is reserved for the "AirDrop" application
   - Ollama is locally installed